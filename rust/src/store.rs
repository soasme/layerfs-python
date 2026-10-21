use layerfs_api::{InitRequest, ProjectApi};
use layerfs_bridge::control::{SdkCall, SdkRefusal, SdkValue};
use layerfs_bridge::provision::{StoreManifest, StoreProfile};
use layerfs_history::{BranchId, HistoryCatalogConfig, HistoryName, LayerStackId};
use layerfs_persistence::{PersistenceConfig, SqlitePersistenceProfile};
use layerfs_storage::StoragePolicy;
use layerfs_store_service::{kernel_guard, OpenRefusal, StoreService};
use layerfs_telemetry::timer::Timing;
use std::collections::HashMap;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, LazyLock, Mutex, Weak};
use std::time::{Duration, Instant};
use tempfile::TempDir;

type Result<T> = std::result::Result<T, SdkRefusal>;
static OPEN: LazyLock<Mutex<HashMap<PathBuf, Weak<Opened>>>> = LazyLock::new(Default::default);
static PROCESS: AtomicU32 = AtomicU32::new(0);

fn check_process() -> Result<()> {
    let pid = std::process::id();
    let original = PROCESS.compare_exchange(0, pid, Ordering::Relaxed, Ordering::Relaxed);
    if original.is_err_and(|original| original != pid) {
        return Err(refuse(
            "ForkedProcess",
            "use a fresh spawned process for Store operations",
        ));
    }
    Ok(())
}

pub fn refuse(code: &str, message: impl ToString) -> SdkRefusal {
    SdkRefusal {
        code: code.into(),
        message: message.to_string(),
        detail: SdkValue::Null,
    }
}

fn failed(error: impl ToString) -> SdkRefusal {
    refuse("Failed", error)
}

fn random<const N: usize>() -> Result<[u8; N]> {
    let key = layerfs_bridge::duplex::generate_keypair().map_err(failed)?;
    Ok(key.public[..N].try_into().expect("authority length"))
}

fn private_file(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options
        .open(path)
        .map_err(failed)?
        .write_all(bytes)
        .map_err(failed)
}

/// Bound metadata reads and reject existing symlinks in the private Store directory.
fn metadata(path: &Path) -> Result<Vec<u8>> {
    let info = fs::symlink_metadata(path).map_err(failed)?;
    if !info.is_file() || info.len() > 16 * 1024 {
        return Err(refuse("InvalidStore", "invalid Store metadata file"));
    }
    let mut bytes = Vec::new();
    File::open(path)
        .map_err(failed)?
        .take(16 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(failed)?;
    if bytes.len() > 16 * 1024 {
        return Err(refuse("InvalidStore", "Store metadata is too large"));
    }
    Ok(bytes)
}

pub struct Opened {
    service: Option<StoreService>,
    overlays: Option<TempDir>,
    project: String,
    pub pid: u32,
}

impl Opened {
    pub fn call(&self, method: String, args: SdkValue) -> Result<SdkValue> {
        let SdkValue::Map(mut fields) = args else {
            return Err(refuse("InvalidInput", "arguments must be a dict"));
        };
        fields.retain(|(name, _)| name != "project");
        fields.push(("project".into(), SdkValue::text(&self.project)));
        layerfs_api::call(
            self.service.as_ref().expect("open service"),
            &SdkCall {
                method,
                args: SdkValue::Map(fields),
            },
        )
    }

    pub fn close(mut self) -> Result<()> {
        if let Some(service) = self.service.take() {
            service.close().map_err(failed)?;
        }
        if let Some(overlays) = self.overlays.take() {
            overlays.close().map_err(failed)?;
        }
        Ok(())
    }
}

impl Drop for Opened {
    fn drop(&mut self) {
        if self.pid != std::process::id() {
            // The parent's threads and SQLite connections cannot be used after fork.
            // Leave its overlay files alone, even if this child discards its copy.
            if let Some(service) = self.service.take() {
                std::mem::forget(service);
            }
            if let Some(overlays) = self.overlays.take() {
                std::mem::forget(overlays);
            }
            return;
        }
        if let Some(service) = self.service.take() {
            let _ = service.close();
        }
    }
}

pub fn open(directory: &Path) -> Result<Arc<Opened>> {
    check_process()?;
    kernel_guard::check(&directory.join("store.sqlite"))
        .map_err(|error| refuse("Unsupported", error))?;
    let directory = directory.canonicalize().map_err(failed)?;
    let mut registry = OPEN.lock().map_err(|_| failed("Store registry poisoned"))?;
    registry.retain(|_, value| value.strong_count() != 0);
    if let Some(opened) = registry.get(&directory).and_then(Weak::upgrade) {
        if opened.pid != std::process::id() {
            return Err(refuse(
                "ForkedProcess",
                "open the Store in a fresh spawned process",
            ));
        }
        return Ok(opened);
    }
    let manifest = StoreManifest::decode(&metadata(&directory.join("manifest.bin"))?)
        .map_err(|error| refuse("InvalidStore", error))?;
    if manifest.profile != StoreProfile::Disposable {
        return Err(refuse(
            "Unsupported",
            "only Disposable Stores are supported",
        ));
    }
    let project = String::from_utf8(metadata(&directory.join("project"))?)
        .map_err(|error| refuse("InvalidStore", error))?;
    HistoryName::new(&project).map_err(|error| refuse("InvalidStore", error))?;
    let overlays = tempfile::Builder::new()
        .prefix("layerfs-python-")
        .tempdir()
        .map_err(failed)?;
    let service = StoreService::open_direct(
        &directory.join("store.sqlite"),
        &manifest.binding,
        manifest.cursor_key,
        &overlays.path().join("overlay.sqlite"),
    )
    .map_err(|error| match error {
        OpenRefusal::Unsupported(error) => refuse("Unsupported", error),
        OpenRefusal::Missing(error) => refuse("NoStore", error),
        OpenRefusal::Failed(error) => failed(error),
    })?;
    let opened = Arc::new(Opened {
        service: Some(service),
        overlays: Some(overlays),
        project,
        pid: std::process::id(),
    });
    registry.insert(directory, Arc::downgrade(&opened));
    Ok(opened)
}

pub fn create(
    directory: &Path,
    source: Option<PathBuf>,
    project: String,
    timeout: f64,
) -> Result<Arc<Opened>> {
    check_process()?;
    let duration = Duration::try_from_secs_f64(timeout)
        .map_err(|_| refuse("InvalidInput", "timeout must be a finite positive number"))?;
    let deadline = Instant::now()
        .checked_add(duration)
        .filter(|_| !duration.is_zero())
        .ok_or_else(|| refuse("InvalidInput", "timeout must be a finite positive number"))?;
    let name = HistoryName::new(&project).map_err(|error| refuse("InvalidInput", error))?;
    // Check before creating any output. The parent must already exist.
    kernel_guard::check(directory).map_err(|error| refuse("Unsupported", error))?;
    let parent = directory
        .parent()
        .unwrap_or(Path::new("."))
        .canonicalize()
        .map_err(failed)?;
    let directory = parent.join(
        directory
            .file_name()
            .ok_or_else(|| refuse("InvalidInput", "Store directory name required"))?,
    );
    let empty;
    let source = match source {
        Some(source) => source.canonicalize().map_err(failed)?,
        None => {
            empty = tempfile::tempdir().map_err(failed)?;
            empty.path().to_path_buf()
        }
    };
    if !source.is_dir() || directory.starts_with(&source) {
        return Err(refuse(
            "InvalidInput",
            "source must be a directory outside the new Store",
        ));
    }
    let mut builder = fs::DirBuilder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder.create(&directory).map_err(|error| {
        if error.kind() == std::io::ErrorKind::AlreadyExists {
            refuse("Exists", error)
        } else {
            failed(error)
        }
    })?;
    // A failed initialization retains its output and exact path, never replaying it.
    let result = (|| {
        let request = InitRequest {
            source,
            store: PersistenceConfig::sqlite(directory.join("store.sqlite"))
                .with_sqlite_profile(SqlitePersistenceProfile::Disposable),
            locator: directory
                .join("store.sqlite")
                .to_str()
                .ok_or_else(|| refuse("InvalidInput", "Store path must be UTF-8"))?
                .into(),
            policy: StoragePolicy::frozen_default(),
            catalog: HistoryCatalogConfig {
                binding_key: random::<32>()?.to_vec(),
                cursor_key: random()?,
                incarnation: 1,
            },
            stack: LayerStackId::from_authority(random()?),
            stack_name: name,
            branch: BranchId::from_authority(random()?),
            branch_name: HistoryName::new("work").expect("valid branch name"),
            scope_seed: random()?,
            deadline,
        };
        let (initialized, _) = Timing::disabled("python.create", |timer| {
            ProjectApi::new().init(request, timer)
        });
        let initialized = initialized.map_err(failed)?;
        private_file(&directory.join("project"), project.as_bytes())?;
        private_file(
            &directory.join("manifest.bin"),
            &initialized.manifest.encode().map_err(failed)?,
        )?;
        open(&directory)
    })();
    result.map_err(|mut error| {
        error.detail = SdkValue::map([("path", SdkValue::text(directory.to_string_lossy()))]);
        error
    })
}
