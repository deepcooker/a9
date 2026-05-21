use std::collections::BTreeMap;
use std::env;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::process::Command;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const TASK_STREAM: &str = "a9:tasks";
const EVENT_STREAM: &str = "a9:events";
const HEARTBEAT_STREAM: &str = "a9:heartbeats";
const WORKER_GROUP: &str = "a9-workers";

#[derive(Debug, Clone, PartialEq, Eq)]
enum Resp {
    Simple(String),
    Error(String),
    Integer(i64),
    Bulk(Option<String>),
    Array(Vec<Resp>),
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct LeasedTask {
    stream_id: String,
    fields: BTreeMap<String, String>,
}

fn encode_command(parts: &[String]) -> Vec<u8> {
    let mut out = format!("*{}\r\n", parts.len()).into_bytes();
    for part in parts {
        out.extend_from_slice(format!("${}\r\n", part.len()).as_bytes());
        out.extend_from_slice(part.as_bytes());
        out.extend_from_slice(b"\r\n");
    }
    out
}

fn redis_roundtrip(addr: &str, parts: &[String], read_timeout: Duration) -> std::io::Result<String> {
    let mut stream = TcpStream::connect(addr)?;
    stream.set_read_timeout(Some(read_timeout))?;
    stream.set_write_timeout(Some(Duration::from_secs(3)))?;
    stream.write_all(&encode_command(parts))?;
    let mut buf = vec![0; 262_144];
    let n = stream.read(&mut buf)?;
    Ok(String::from_utf8_lossy(&buf[..n]).to_string())
}

fn now_ms() -> String {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .to_string()
}

fn read_line(input: &[u8], pos: &mut usize) -> Result<String, String> {
    let start = *pos;
    while *pos + 1 < input.len() {
        if input[*pos] == b'\r' && input[*pos + 1] == b'\n' {
            let line = String::from_utf8_lossy(&input[start..*pos]).to_string();
            *pos += 2;
            return Ok(line);
        }
        *pos += 1;
    }
    Err("unterminated RESP line".to_string())
}

fn parse_resp_at(input: &[u8], pos: &mut usize) -> Result<Resp, String> {
    if *pos >= input.len() {
        return Err("empty RESP input".to_string());
    }
    let tag = input[*pos];
    *pos += 1;
    match tag {
        b'+' => Ok(Resp::Simple(read_line(input, pos)?)),
        b'-' => Ok(Resp::Error(read_line(input, pos)?)),
        b':' => {
            let value = read_line(input, pos)?
                .parse::<i64>()
                .map_err(|err| format!("invalid integer: {err}"))?;
            Ok(Resp::Integer(value))
        }
        b'$' => {
            let len = read_line(input, pos)?
                .parse::<isize>()
                .map_err(|err| format!("invalid bulk length: {err}"))?;
            if len < 0 {
                return Ok(Resp::Bulk(None));
            }
            let len = len as usize;
            if *pos + len + 2 > input.len() {
                return Err("bulk string longer than input".to_string());
            }
            let value = String::from_utf8_lossy(&input[*pos..*pos + len]).to_string();
            *pos += len;
            if input.get(*pos..*pos + 2) != Some(b"\r\n") {
                return Err("bulk string missing CRLF".to_string());
            }
            *pos += 2;
            Ok(Resp::Bulk(Some(value)))
        }
        b'*' => {
            let len = read_line(input, pos)?
                .parse::<isize>()
                .map_err(|err| format!("invalid array length: {err}"))?;
            if len < 0 {
                return Ok(Resp::Array(Vec::new()));
            }
            let mut values = Vec::with_capacity(len as usize);
            for _ in 0..len {
                values.push(parse_resp_at(input, pos)?);
            }
            Ok(Resp::Array(values))
        }
        other => Err(format!("unknown RESP tag: {}", other as char)),
    }
}

fn parse_resp(input: &str) -> Result<Resp, String> {
    let mut pos = 0;
    parse_resp_at(input.as_bytes(), &mut pos)
}

fn bulk_str(value: &Resp) -> Option<&str> {
    match value {
        Resp::Bulk(Some(text)) | Resp::Simple(text) => Some(text.as_str()),
        _ => None,
    }
}

fn extract_first_task(resp: &Resp) -> Option<LeasedTask> {
    let Resp::Array(streams) = resp else {
        return None;
    };
    let stream = match streams.first()? {
        Resp::Array(items) => items,
        _ => return None,
    };
    let messages = match stream.get(1)? {
        Resp::Array(messages) => messages,
        _ => return None,
    };
    let message = match messages.first()? {
        Resp::Array(items) => items,
        _ => return None,
    };
    let stream_id = bulk_str(message.first()?)?.to_string();
    let raw_fields = match message.get(1)? {
        Resp::Array(fields) => fields,
        _ => return None,
    };
    let mut fields = BTreeMap::new();
    for pair in raw_fields.chunks(2) {
        if let [key, value] = pair {
            if let (Some(key), Some(value)) = (bulk_str(key), bulk_str(value)) {
                fields.insert(key.to_string(), value.to_string());
            }
        }
    }
    Some(LeasedTask { stream_id, fields })
}

fn lease_task(addr: &str, worker_id: &str, block_ms: u64) -> Result<Option<LeasedTask>, String> {
    let response = redis_roundtrip(
        addr,
        &[
            "XREADGROUP".into(),
            "GROUP".into(),
            WORKER_GROUP.into(),
            worker_id.into(),
            "COUNT".into(),
            "1".into(),
            "BLOCK".into(),
            block_ms.to_string(),
            "STREAMS".into(),
            TASK_STREAM.into(),
            ">".into(),
        ],
        Duration::from_millis(block_ms + 1000),
    )
    .map_err(|err| err.to_string())?;
    if response.starts_with("$-1") || response.starts_with("*0") {
        return Ok(None);
    }
    let parsed = parse_resp(&response)?;
    Ok(extract_first_task(&parsed))
}

fn xadd_event(
    addr: &str,
    event_type: &str,
    task: &LeasedTask,
    fields: &[(&str, String)],
) -> Result<(), String> {
    let mut parts = vec![
        "XADD".to_string(),
        EVENT_STREAM.to_string(),
        "*".to_string(),
        "type".to_string(),
        event_type.to_string(),
        "stream_id".to_string(),
        task.stream_id.clone(),
        "task_id".to_string(),
        task.fields.get("task_id").cloned().unwrap_or_default(),
        "created_at_ms".to_string(),
        now_ms(),
    ];
    for (key, value) in fields {
        parts.push((*key).to_string());
        parts.push(value.clone());
    }
    redis_roundtrip(addr, &parts, Duration::from_secs(3)).map_err(|err| err.to_string())?;
    Ok(())
}

fn heartbeat(addr: &str, worker_id: &str, state: &str) -> Result<(), String> {
    redis_roundtrip(
        addr,
        &[
            "XADD".into(),
            HEARTBEAT_STREAM.into(),
            "*".into(),
            "worker_id".into(),
            worker_id.into(),
            "state".into(),
            state.into(),
            "created_at_ms".into(),
            now_ms(),
        ],
        Duration::from_secs(3),
    )
    .map_err(|err| err.to_string())?;
    Ok(())
}

fn ack(addr: &str, stream_id: &str) -> Result<(), String> {
    redis_roundtrip(
        addr,
        &[
            "XACK".into(),
            TASK_STREAM.into(),
            WORKER_GROUP.into(),
            stream_id.into(),
        ],
        Duration::from_secs(3),
    )
    .map_err(|err| err.to_string())?;
    Ok(())
}

fn run_shell_worker(task: &LeasedTask, command: &str, timeout_seconds: u64) -> Result<i32, String> {
    let prompt = task.fields.get("prompt").cloned().unwrap_or_default();
    let task_id = task.fields.get("task_id").cloned().unwrap_or_default();
    let mut child = Command::new("sh")
        .arg("-lc")
        .arg(command)
        .env("A9_STREAM_ID", &task.stream_id)
        .env("A9_TASK_ID", task_id)
        .env("A9_PROMPT", prompt)
        .spawn()
        .map_err(|err| format!("spawn failed: {err}"))?;

    let deadline = SystemTime::now() + Duration::from_secs(timeout_seconds);
    loop {
        if let Some(status) = child.try_wait().map_err(|err| err.to_string())? {
            return Ok(status.code().unwrap_or(1));
        }
        if SystemTime::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!("worker timed out after {timeout_seconds}s"));
        }
        std::thread::sleep(Duration::from_millis(200));
    }
}

fn run_once(
    addr: &str,
    worker_id: &str,
    command: &str,
    block_ms: u64,
    timeout_seconds: u64,
) -> Result<i32, String> {
    heartbeat(addr, worker_id, "leasing")?;
    let Some(task) = lease_task(addr, worker_id, block_ms)? else {
        heartbeat(addr, worker_id, "idle")?;
        println!("no task leased");
        return Ok(0);
    };
    heartbeat(addr, worker_id, "running")?;
    xadd_event(addr, "task_started", &task, &[("worker_id", worker_id.to_string())])?;
    match run_shell_worker(&task, command, timeout_seconds) {
        Ok(0) => {
            xadd_event(addr, "task_completed", &task, &[("worker_id", worker_id.to_string())])?;
            ack(addr, &task.stream_id)?;
            heartbeat(addr, worker_id, "completed")?;
            println!("completed {}", task.stream_id);
            Ok(0)
        }
        Ok(code) => {
            xadd_event(
                addr,
                "task_failed",
                &task,
                &[("worker_id", worker_id.to_string()), ("return_code", code.to_string())],
            )?;
            ack(addr, &task.stream_id)?;
            heartbeat(addr, worker_id, "failed")?;
            Err(format!("worker exited with {code}"))
        }
        Err(err) => {
            xadd_event(
                addr,
                "task_failed",
                &task,
                &[("worker_id", worker_id.to_string()), ("reason", err.clone())],
            )?;
            ack(addr, &task.stream_id)?;
            heartbeat(addr, worker_id, "failed")?;
            Err(err)
        }
    }
}

fn usage() -> ! {
    eprintln!(
        "usage:
  a9-worker run-once [--worker-id ID] [--command CMD] [--block-ms N] [--timeout-seconds N]
  a9-worker parse-lease <resp-file>"
    );
    std::process::exit(2);
}

fn main() {
    let addr = env::var("A9_REDIS_ADDR").unwrap_or_else(|_| "127.0.0.1:63799".to_string());
    let mut args = env::args().skip(1);
    let Some(command_name) = args.next() else {
        usage();
    };
    let result = match command_name.as_str() {
        "run-once" => {
            let mut worker_id =
                env::var("A9_WORKER_ID").unwrap_or_else(|_| "a9-rust-worker".to_string());
            let mut command = env::var("A9_NATIVE_WORKER_CMD").unwrap_or_else(|_| {
                "python3 scripts/a9_supervisor.py run-one --auto-next".to_string()
            });
            let mut block_ms = 1000_u64;
            let mut timeout_seconds = 3600_u64;
            while let Some(flag) = args.next() {
                match flag.as_str() {
                    "--worker-id" => worker_id = args.next().unwrap_or_else(|| usage()),
                    "--command" => command = args.next().unwrap_or_else(|| usage()),
                    "--block-ms" => {
                        block_ms = args
                            .next()
                            .unwrap_or_else(|| usage())
                            .parse()
                            .unwrap_or_else(|_| usage())
                    }
                    "--timeout-seconds" => {
                        timeout_seconds = args
                            .next()
                            .unwrap_or_else(|| usage())
                            .parse()
                            .unwrap_or_else(|_| usage())
                    }
                    _ => usage(),
                }
            }
            run_once(&addr, &worker_id, &command, block_ms, timeout_seconds)
        }
        "parse-lease" => {
            let Some(path) = args.next() else {
                usage();
            };
            let text = std::fs::read_to_string(path).map_err(|err| err.to_string());
            text.and_then(|text| {
                let parsed = parse_resp(&text)?;
                let task = extract_first_task(&parsed).ok_or_else(|| "no task".to_string())?;
                println!("stream_id={}", task.stream_id);
                for (key, value) in task.fields {
                    println!("{key}={value}");
                }
                Ok(0)
            })
        }
        _ => usage(),
    };
    match result {
        Ok(code) => std::process::exit(code),
        Err(err) => {
            eprintln!("{err}");
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_simple_resp_integer() {
        assert_eq!(parse_resp(":42\r\n").unwrap(), Resp::Integer(42));
    }

    #[test]
    fn extracts_xreadgroup_task() {
        let raw = "*1\r\n*2\r\n$8\r\na9:tasks\r\n*1\r\n*2\r\n$15\r\n1710000000000-0\r\n*8\r\n$7\r\ntask_id\r\n$5\r\nalpha\r\n$6\r\nprompt\r\n$11\r\ncopy things\r\n$13\r\ncreated_at_ms\r\n$13\r\n1710000000000\r\n$6\r\nstatus\r\n$6\r\nqueued\r\n";
        let resp = parse_resp(raw).unwrap();
        let task = extract_first_task(&resp).unwrap();
        assert_eq!(task.stream_id, "1710000000000-0");
        assert_eq!(task.fields.get("task_id").unwrap(), "alpha");
        assert_eq!(task.fields.get("prompt").unwrap(), "copy things");
    }

    #[test]
    fn encodes_redis_command() {
        let encoded = encode_command(&["PING".to_string(), "hello".to_string()]);
        assert_eq!(String::from_utf8(encoded).unwrap(), "*2\r\n$4\r\nPING\r\n$5\r\nhello\r\n");
    }
}
