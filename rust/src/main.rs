//! Keep daemon behavior in the pinned upstream library.
fn main() -> std::process::ExitCode {
    layerfs_daemon::application::main()
}
