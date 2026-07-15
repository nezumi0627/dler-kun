use std::{
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Mutex,
};
use tauri::Manager;

struct BackendProcess(Mutex<Option<Child>>);

fn main() {
    tauri::Builder::default()
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from("."));

            let child = Command::new("python")
                .args([
                    "-m",
                    "dler_kun",
                    "web",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8787",
                    "--no-open",
                ])
                .current_dir(&project_root)
                .env("PYTHONPATH", project_root.join("src"))
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn();

            if let Ok(child) = child {
                let state = app.state::<BackendProcess>();
                *state.0.lock().expect("backend process lock") = Some(child);
            }

            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::CloseRequested { .. }) {
                let state = window.state::<BackendProcess>();
                let child = {
                    let mut backend = state.0.lock().expect("backend process lock");
                    backend.take()
                };
                if let Some(mut child) = child {
                    let _ = child.kill();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running dler-kun");
}
