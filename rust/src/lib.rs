mod convert;
mod store;

use layerfs_bridge::control::SdkRefusal;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

#[pyclass(frozen, module = "layerfs._native")]
struct NativeStore {
    state: Mutex<Option<Arc<store::Opened>>>,
    pid: u32,
}

impl NativeStore {
    fn from_opened(opened: Arc<store::Opened>) -> Self {
        Self {
            state: Mutex::new(Some(opened)),
            pid: std::process::id(),
        }
    }

    fn process(&self) -> Result<(), SdkRefusal> {
        if self.pid != std::process::id() {
            return Err(store::refuse(
                "ForkedProcess",
                "Store handles cannot cross fork; use a spawned process",
            ));
        }
        Ok(())
    }

    fn opened(&self) -> Result<Arc<store::Opened>, SdkRefusal> {
        self.process()?;
        self.state
            .lock()
            .map_err(|_| store::refuse("Failed", "Store handle poisoned"))?
            .clone()
            .ok_or_else(|| store::refuse("Closed", "Store is closed"))
    }
}

#[pymethods]
impl NativeStore {
    #[staticmethod]
    fn open(py: Python<'_>, path: PathBuf) -> PyResult<Self> {
        py.detach(|| store::open(&path))
            .map(Self::from_opened)
            .map_err(|error| convert::error(py, error))
    }

    #[staticmethod]
    #[pyo3(signature = (path, source=None, project="default".to_owned(), timeout=60.0))]
    fn create(
        py: Python<'_>,
        path: PathBuf,
        source: Option<PathBuf>,
        project: String,
        timeout: f64,
    ) -> PyResult<Self> {
        py.detach(|| store::create(&path, source, project, timeout))
            .map(Self::from_opened)
            .map_err(|error| convert::error(py, error))
    }

    fn call(
        &self,
        py: Python<'_>,
        method: String,
        args: &Bound<'_, PyDict>,
    ) -> PyResult<Py<PyAny>> {
        let args = convert::from_python(args.as_any(), 0)?;
        let result = py
            .detach(|| self.opened()?.call(method, args))
            .map_err(|error| convert::error(py, error))?;
        convert::to_python(py, result)
    }

    #[getter]
    fn closed(&self, py: Python<'_>) -> PyResult<bool> {
        self.process().map_err(|error| convert::error(py, error))?;
        Ok(self
            .state
            .lock()
            .map_err(|_| convert::error(py, store::refuse("Failed", "Store handle poisoned")))?
            .is_none())
    }

    fn close(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| {
            self.process()?;
            let opened = self
                .state
                .lock()
                .map_err(|_| store::refuse("Failed", "Store handle poisoned"))?
                .take();
            if let Some(opened) = opened {
                if let Ok(opened) = Arc::try_unwrap(opened) {
                    return opened.close();
                }
            }
            Ok(())
        })
        .map_err(|error| convert::error(py, error))
    }
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<NativeStore>()?;
    module.add(
        "LayerFSError",
        module.py().get_type::<convert::LayerFSError>(),
    )?;
    Ok(())
}
