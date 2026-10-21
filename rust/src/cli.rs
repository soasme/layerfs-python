//! Friendly package CLI; configured daemon execution stays upstream.
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.is_empty() || (args.len() == 1 && (args[0] == "--help" || args[0] == "-h")) {
        println!(
            "LayerFS {}\n\n\
             Usage: layerfs --config <protected-file>\n\n\
             Launch the upstream LayerFS filesystem daemon.\n\
             Daemon operation requires Linux, FUSE, and a protected configuration file.\n\n\
             Options:\n  \
             --config <protected-file>  Use the upstream daemon configuration\n  \
             -h, --help                 Show this help\n  \
             --version                  Show the package version",
            env!("CARGO_PKG_VERSION")
        );
        return ExitCode::SUCCESS;
    }
    if args.len() == 1 && args[0] == "--version" {
        println!("layerfs {}", env!("CARGO_PKG_VERSION"));
        return ExitCode::SUCCESS;
    }
    layerfs_daemon::application::main()
}
