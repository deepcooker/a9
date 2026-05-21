use std::env;
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

const DEFAULT_MODEL: &str = "gpt-5.5";
const DEFAULT_API_URL: &str = "http://127.0.0.1:8080/v1";
const DEFAULT_PHASE: &str = "reference_scan";

#[derive(Debug, Clone)]
struct Config {
    api_url: String,
    model: String,
    supervisor: PathBuf,
    root: PathBuf,
}

#[derive(Debug, Clone)]
struct Session {
    id: String,
    task_id: String,
    status: String,
    prompt: String,
    created_at_ms: u128,
    updated_at_ms: u128,
    queue_path: String,
    run_dir: String,
    parent_session_id: String,
    turn: u32,
}

#[derive(Debug, Default)]
struct SubmitOptions {
    task_id: Option<String>,
    phase: String,
    run: bool,
    checks: Vec<String>,
}

fn usage() -> ! {
    eprintln!(
        "usage:
  a9-client init [--api-url URL] [--model MODEL]
  a9-client config
  a9-client submit [--task-id ID] [--phase PHASE] [--check CMD] [--run] <prompt...>
  a9-client status [latest|SESSION_ID]
  a9-client resume [latest|SESSION_ID] [--run] <extra prompt...>

Environment:
  A9_ROOT          repository root (defaults to current directory)
  A9_CONFIG       config path (defaults to .a9/client/config.json)
  A9_SUPERVISOR   supervisor path (defaults to scripts/a9_supervisor.py)"
    );
    std::process::exit(2);
}

fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}

fn repo_root() -> PathBuf {
    env::var("A9_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| env::current_dir().unwrap_or_else(|_| PathBuf::from(".")))
}

fn client_dir(root: &Path) -> PathBuf {
    root.join(".a9").join("client")
}

fn sessions_dir(root: &Path) -> PathBuf {
    client_dir(root).join("sessions")
}

fn latest_path(root: &Path) -> PathBuf {
    client_dir(root).join("latest")
}

fn config_path(root: &Path) -> PathBuf {
    env::var("A9_CONFIG")
        .map(PathBuf::from)
        .unwrap_or_else(|_| client_dir(root).join("config.json"))
}

fn supervisor_path(root: &Path) -> PathBuf {
    env::var("A9_SUPERVISOR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| root.join("scripts").join("a9_supervisor.py"))
}

fn ensure_client_dirs(root: &Path) -> io::Result<()> {
    fs::create_dir_all(sessions_dir(root))
}

fn json_escape(value: &str) -> String {
    let mut out = String::with_capacity(value.len() + 8);
    for ch in value.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c.is_control() => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out
}

fn json_string_value(text: &str, key: &str) -> Option<String> {
    let needle = format!("\"{}\"", key);
    let start = text.find(&needle)?;
    let after_key = &text[start + needle.len()..];
    let colon = after_key.find(':')?;
    let mut chars = after_key[colon + 1..].trim_start().chars();
    if chars.next()? != '"' {
        return None;
    }
    let mut out = String::new();
    let mut escaped = false;
    for ch in chars {
        if escaped {
            match ch {
                '"' => out.push('"'),
                '\\' => out.push('\\'),
                'n' => out.push('\n'),
                'r' => out.push('\r'),
                't' => out.push('\t'),
                other => out.push(other),
            }
            escaped = false;
        } else if ch == '\\' {
            escaped = true;
        } else if ch == '"' {
            return Some(out);
        } else {
            out.push(ch);
        }
    }
    None
}

fn json_u128_value(text: &str, key: &str) -> Option<u128> {
    let needle = format!("\"{}\"", key);
    let start = text.find(&needle)?;
    let after_key = &text[start + needle.len()..];
    let colon = after_key.find(':')?;
    let digits: String = after_key[colon + 1..]
        .trim_start()
        .chars()
        .take_while(|ch| ch.is_ascii_digit())
        .collect();
    digits.parse().ok()
}

fn json_u32_value(text: &str, key: &str) -> Option<u32> {
    json_u128_value(text, key).and_then(|value| u32::try_from(value).ok())
}

fn load_config(root: &Path) -> Config {
    let path = config_path(root);
    let text = fs::read_to_string(path).unwrap_or_default();
    Config {
        api_url: env::var("A9_API_URL")
            .ok()
            .or_else(|| json_string_value(&text, "api_url"))
            .unwrap_or_else(|| DEFAULT_API_URL.to_string()),
        model: env::var("A9_MODEL")
            .ok()
            .or_else(|| json_string_value(&text, "model"))
            .unwrap_or_else(|| DEFAULT_MODEL.to_string()),
        supervisor: supervisor_path(root),
        root: root.to_path_buf(),
    }
}

fn write_config(root: &Path, api_url: &str, model: &str) -> io::Result<PathBuf> {
    ensure_client_dirs(root)?;
    let path = config_path(root);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let payload = format!(
        "{{\n  \"api_url\": \"{}\",\n  \"model\": \"{}\",\n  \"notes\": \"A9 client config; API key is read from A9_API_KEY or your model gateway.\"\n}}\n",
        json_escape(api_url),
        json_escape(model)
    );
    fs::write(&path, payload)?;
    Ok(path)
}

fn slugify(value: &str) -> String {
    let mut out = String::new();
    let mut last_dash = false;
    for ch in value.chars() {
        let mapped = if ch.is_ascii_alphanumeric() || ch == '_' || ch == '.' {
            Some(ch.to_ascii_lowercase())
        } else if ch == '-' || ch.is_whitespace() {
            Some('-')
        } else {
            None
        };
        if let Some(c) = mapped {
            if c == '-' {
                if !last_dash && !out.is_empty() {
                    out.push(c);
                }
                last_dash = true;
            } else {
                out.push(c);
                last_dash = false;
            }
        }
        if out.len() >= 64 {
            break;
        }
    }
    while out.ends_with('-') {
        out.pop();
    }
    if out.is_empty() {
        format!("task-{}", now_ms())
    } else {
        out
    }
}

fn session_id() -> String {
    format!("a9s-{}", now_ms())
}

fn session_path(root: &Path, id: &str) -> PathBuf {
    sessions_dir(root).join(id).join("session.json")
}

fn session_prompt_path(root: &Path, id: &str) -> PathBuf {
    sessions_dir(root).join(id).join("prompt.md")
}

fn write_session(root: &Path, session: &Session) -> io::Result<()> {
    let dir = sessions_dir(root).join(&session.id);
    fs::create_dir_all(&dir)?;
    fs::write(session_prompt_path(root, &session.id), &session.prompt)?;
    let payload = format!(
        concat!(
            "{{\n",
            "  \"id\": \"{}\",\n",
            "  \"task_id\": \"{}\",\n",
            "  \"status\": \"{}\",\n",
            "  \"created_at_ms\": {},\n",
            "  \"updated_at_ms\": {},\n",
            "  \"queue_path\": \"{}\",\n",
            "  \"run_dir\": \"{}\",\n",
            "  \"parent_session_id\": \"{}\",\n",
            "  \"turn\": {},\n",
            "  \"prompt_path\": \"{}\"\n",
            "}}\n"
        ),
        json_escape(&session.id),
        json_escape(&session.task_id),
        json_escape(&session.status),
        session.created_at_ms,
        session.updated_at_ms,
        json_escape(&session.queue_path),
        json_escape(&session.run_dir),
        json_escape(&session.parent_session_id),
        session.turn,
        json_escape(&session_prompt_path(root, &session.id).display().to_string())
    );
    fs::write(session_path(root, &session.id), payload)?;
    fs::write(latest_path(root), &session.id)?;
    Ok(())
}

fn read_session(root: &Path, id: &str) -> io::Result<Session> {
    let actual_id = if id == "latest" {
        fs::read_to_string(latest_path(root))?.trim().to_string()
    } else {
        id.to_string()
    };
    let text = fs::read_to_string(session_path(root, &actual_id))?;
    let prompt = fs::read_to_string(session_prompt_path(root, &actual_id)).unwrap_or_default();
    Ok(Session {
        id: json_string_value(&text, "id").unwrap_or(actual_id),
        task_id: json_string_value(&text, "task_id").unwrap_or_default(),
        status: json_string_value(&text, "status").unwrap_or_else(|| "unknown".to_string()),
        prompt,
        created_at_ms: json_u128_value(&text, "created_at_ms").unwrap_or(0),
        updated_at_ms: json_u128_value(&text, "updated_at_ms").unwrap_or(0),
        queue_path: json_string_value(&text, "queue_path").unwrap_or_default(),
        run_dir: json_string_value(&text, "run_dir").unwrap_or_default(),
        parent_session_id: json_string_value(&text, "parent_session_id").unwrap_or_default(),
        turn: json_u32_value(&text, "turn").unwrap_or(1),
    })
}

fn run_supervisor(config: &Config, args: &[String]) -> io::Result<(i32, String)> {
    let output = Command::new(&config.supervisor)
        .args(args)
        .current_dir(&config.root)
        .output()?;
    let mut text = String::new();
    text.push_str(&String::from_utf8_lossy(&output.stdout));
    text.push_str(&String::from_utf8_lossy(&output.stderr));
    Ok((output.status.code().unwrap_or(1), text))
}

fn enqueue_task(config: &Config, task_id: &str, prompt: &str, opts: &SubmitOptions) -> io::Result<String> {
    let mut args = vec![
        "enqueue".to_string(),
        task_id.to_string(),
        prompt.to_string(),
        "--phase".to_string(),
        opts.phase.clone(),
    ];
    for check in &opts.checks {
        args.push("--check".to_string());
        args.push(check.clone());
    }
    let (code, text) = run_supervisor(config, &args)?;
    if code != 0 {
        return Err(io::Error::new(io::ErrorKind::Other, text));
    }
    Ok(text.trim().to_string())
}

fn refresh_from_done(root: &Path, session: &mut Session) {
    let done_path = root
        .join(".a9")
        .join("tasks")
        .join("done")
        .join(format!("{}.json", session.task_id));
    let Ok(text) = fs::read_to_string(done_path) else {
        return;
    };
    if let Some(status) = json_string_value(&text, "status") {
        session.status = status;
    }
    if let Some(run_dir) = json_string_value(&text, "run_dir") {
        session.run_dir = run_dir;
    }
    session.updated_at_ms = now_ms();
}

fn parse_submit(args: &[String]) -> (SubmitOptions, String) {
    let mut opts = SubmitOptions {
        phase: DEFAULT_PHASE.to_string(),
        ..SubmitOptions::default()
    };
    let mut prompt_parts = Vec::new();
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--task-id" => {
                i += 1;
                if i >= args.len() {
                    usage();
                }
                opts.task_id = Some(args[i].clone());
            }
            "--phase" => {
                i += 1;
                if i >= args.len() {
                    usage();
                }
                opts.phase = args[i].clone();
            }
            "--check" => {
                i += 1;
                if i >= args.len() {
                    usage();
                }
                opts.checks.push(args[i].clone());
            }
            "--run" => opts.run = true,
            value => prompt_parts.push(value.to_string()),
        }
        i += 1;
    }
    let prompt = prompt_parts.join(" ").trim().to_string();
    if prompt.is_empty() {
        usage();
    }
    (opts, prompt)
}

fn cmd_init(root: &Path, args: &[String]) -> io::Result<()> {
    let mut api_url = DEFAULT_API_URL.to_string();
    let mut model = DEFAULT_MODEL.to_string();
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--api-url" => {
                i += 1;
                if i >= args.len() {
                    usage();
                }
                api_url = args[i].clone();
            }
            "--model" => {
                i += 1;
                if i >= args.len() {
                    usage();
                }
                model = args[i].clone();
            }
            _ => usage(),
        }
        i += 1;
    }
    let path = write_config(root, &api_url, &model)?;
    println!("{}", path.display());
    Ok(())
}

fn cmd_config(config: &Config) {
    println!("root={}", config.root.display());
    println!("config={}", config_path(&config.root).display());
    println!("api_url={}", config.api_url);
    println!("model={}", config.model);
    println!("supervisor={}", config.supervisor.display());
}

fn cmd_submit(config: &Config, args: &[String]) -> io::Result<()> {
    ensure_client_dirs(&config.root)?;
    let (opts, prompt) = parse_submit(args);
    let id = session_id();
    let task_id = opts
        .task_id
        .clone()
        .unwrap_or_else(|| format!("client-{}-{}", slugify(&prompt), now_ms()));
    let queue_path = enqueue_task(config, &task_id, &prompt, &opts)?;
    let mut session = Session {
        id,
        task_id,
        status: "queued".to_string(),
        prompt,
        created_at_ms: now_ms(),
        updated_at_ms: now_ms(),
        queue_path,
        run_dir: String::new(),
        parent_session_id: String::new(),
        turn: 1,
    };
    if opts.run {
        let (code, text) = run_supervisor(config, &["run-one".to_string()])?;
        if code != 0 {
            session.status = "run-failed".to_string();
        }
        refresh_from_done(&config.root, &mut session);
        if session.status == "queued" {
            session.status = if code == 0 { "submitted" } else { "run-failed" }.to_string();
        }
        if !text.trim().is_empty() {
            print!("{}", text);
        }
    }
    write_session(&config.root, &session)?;
    println!("session={}", session.id);
    println!("task_id={}", session.task_id);
    println!("status={}", session.status);
    println!("queue_path={}", session.queue_path);
    if !session.run_dir.is_empty() {
        println!("run_dir={}", session.run_dir);
    }
    Ok(())
}

fn cmd_status(config: &Config, id: &str) -> io::Result<()> {
    let mut session = read_session(&config.root, id)?;
    refresh_from_done(&config.root, &mut session);
    write_session(&config.root, &session)?;
    println!("session={}", session.id);
    println!("task_id={}", session.task_id);
    println!("status={}", session.status);
    println!("turn={}", session.turn);
    println!("queue_path={}", session.queue_path);
    if !session.run_dir.is_empty() {
        println!("run_dir={}", session.run_dir);
    }
    Ok(())
}

fn cmd_resume(config: &Config, args: &[String]) -> io::Result<()> {
    if args.is_empty() {
        usage();
    }
    let base_id = &args[0];
    let mut run = false;
    let mut extra_parts = Vec::new();
    for arg in &args[1..] {
        if arg == "--run" {
            run = true;
        } else {
            extra_parts.push(arg.clone());
        }
    }
    let extra = extra_parts.join(" ");
    if extra.trim().is_empty() {
        usage();
    }
    let parent = read_session(&config.root, base_id)?;
    let prompt = format!(
        "Continue A9 client session {} / task {}.\n\nPrevious prompt:\n{}\n\nNew instruction:\n{}",
        parent.id, parent.task_id, parent.prompt, extra
    );
    let opts = SubmitOptions {
        task_id: Some(format!("{}-resume-{}", parent.task_id, now_ms())),
        phase: DEFAULT_PHASE.to_string(),
        run,
        checks: Vec::new(),
    };
    let id = session_id();
    let task_id = opts.task_id.clone().unwrap();
    let queue_path = enqueue_task(config, &task_id, &prompt, &opts)?;
    let mut session = Session {
        id,
        task_id,
        status: "queued".to_string(),
        prompt,
        created_at_ms: now_ms(),
        updated_at_ms: now_ms(),
        queue_path,
        run_dir: String::new(),
        parent_session_id: parent.id,
        turn: parent.turn + 1,
    };
    if run {
        let (code, text) = run_supervisor(config, &["run-one".to_string()])?;
        if code != 0 {
            session.status = "run-failed".to_string();
        }
        refresh_from_done(&config.root, &mut session);
        if !text.trim().is_empty() {
            print!("{}", text);
        }
    }
    write_session(&config.root, &session)?;
    println!("session={}", session.id);
    println!("parent_session={}", session.parent_session_id);
    println!("task_id={}", session.task_id);
    println!("status={}", session.status);
    Ok(())
}

fn run() -> io::Result<()> {
    let root = repo_root();
    let mut args: Vec<String> = env::args().skip(1).collect();
    if args.is_empty() {
        usage();
    }
    let command = args.remove(0);
    match command.as_str() {
        "init" => cmd_init(&root, &args),
        "config" => {
            let config = load_config(&root);
            cmd_config(&config);
            Ok(())
        }
        "submit" => {
            let config = load_config(&root);
            cmd_submit(&config, &args)
        }
        "status" => {
            let config = load_config(&root);
            let id = args.first().map(String::as_str).unwrap_or("latest");
            cmd_status(&config, id)
        }
        "resume" => {
            let config = load_config(&root);
            cmd_resume(&config, &args)
        }
        _ => usage(),
    }
}

fn main() {
    if let Err(err) = run() {
        let _ = writeln!(io::stderr(), "a9-client: {err}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn slugify_keeps_bounded_cli_ids() {
        assert_eq!(slugify("Fix Redis stream status!"), "fix-redis-stream-status");
        assert!(slugify("!!!").starts_with("task-"));
        assert!(slugify(&"a".repeat(100)).len() <= 64);
    }

    #[test]
    fn json_string_parser_handles_escaped_values() {
        let text = r#"{"api_url":"http://x/v1","model":"gpt-5.5","note":"a\nb"}"#;
        assert_eq!(json_string_value(text, "api_url").as_deref(), Some("http://x/v1"));
        assert_eq!(json_string_value(text, "model").as_deref(), Some("gpt-5.5"));
        assert_eq!(json_string_value(text, "note").as_deref(), Some("a\nb"));
    }

    #[test]
    fn submit_parser_collects_flags_and_prompt() {
        let args = vec![
            "--task-id".to_string(),
            "abc".to_string(),
            "--phase".to_string(),
            "test".to_string(),
            "--check".to_string(),
            "cargo test".to_string(),
            "--run".to_string(),
            "do".to_string(),
            "work".to_string(),
        ];
        let (opts, prompt) = parse_submit(&args);
        assert_eq!(opts.task_id.as_deref(), Some("abc"));
        assert_eq!(opts.phase, "test");
        assert_eq!(opts.checks, vec!["cargo test"]);
        assert!(opts.run);
        assert_eq!(prompt, "do work");
    }

    #[test]
    fn submit_parser_defaults_to_copy_pipeline_start() {
        let args = vec!["copy".to_string(), "codex".to_string()];
        let (opts, prompt) = parse_submit(&args);
        assert_eq!(opts.phase, "reference_scan");
        assert_eq!(prompt, "copy codex");
    }
}
