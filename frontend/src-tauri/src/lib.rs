use std::sync::Mutex;

use tauri::Manager;
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

/// Хендл фонового backend-процесса (shorts-backend.exe) — храним, чтобы
/// суметь его остановить при закрытии окна. Без этого процесс оставался бы
/// висеть в фоне после закрытия приложения (uvicorn сам не завершается,
/// когда его никто не спрашивает).
struct BackendProcess(Mutex<Option<CommandChild>>);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            // Поднимаем backend как sidecar-процесс при старте окна — тот
            // же самый .exe, что собран через PyInstaller (шаг 1), слушает
            // на 127.0.0.1:8000 (RUNNER_MODE=local зашит в desktop_main.py).
            let sidecar = app.shell().sidecar("shorts-backend")?;
            let (mut rx, child) = sidecar.spawn().expect("не удалось запустить shorts-backend.exe");

            let state = app.state::<BackendProcess>();
            *state.0.lock().unwrap() = Some(child);

            // Лог backend-процесса пробрасываем в лог самого Tauri-приложения —
            // полезно при отладке (запуск, миграции, ошибки ffmpeg и т.д.
            // видно в тех же логах, что и остальное приложение).
            tauri::async_runtime::spawn(async move {
                use tauri_plugin_shell::process::CommandEvent;
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            log::info!("[backend] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Stderr(line) => {
                            log::info!("[backend] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Error(err) => {
                            log::error!("[backend] ошибка процесса: {}", err);
                        }
                        CommandEvent::Terminated(payload) => {
                            log::info!("[backend] завершился с кодом {:?}", payload.code);
                        }
                        _ => {}
                    }
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            // Останавливаем backend, когда закрывают главное (и единственное)
            // окно приложения — иначе процесс продолжил бы работать в фоне
            // и держать порт 8000 занятым при следующем запуске.
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                let state = window.state::<BackendProcess>();
                let child = state.0.lock().unwrap().take();
                if let Some(child) = child {
                    let _ = child.kill();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
