use std::env;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const TASK_STREAM: &str = "a9:tasks";
const EVENT_STREAM: &str = "a9:events";
const HEARTBEAT_STREAM: &str = "a9:heartbeats";
const WORKER_GROUP: &str = "a9-workers";

fn encode_command(parts: &[String]) -> Vec<u8> {
    let mut out = format!("*{}\r\n", parts.len()).into_bytes();
    for part in parts {
        out.extend_from_slice(format!("${}\r\n", part.len()).as_bytes());
        out.extend_from_slice(part.as_bytes());
        out.extend_from_slice(b"\r\n");
    }
    out
}

fn redis_roundtrip(addr: &str, parts: &[String]) -> std::io::Result<String> {
    let mut stream = TcpStream::connect(addr)?;
    stream.set_read_timeout(Some(Duration::from_secs(3)))?;
    stream.set_write_timeout(Some(Duration::from_secs(3)))?;
    stream.write_all(&encode_command(parts))?;
    let mut buf = vec![0; 65536];
    let n = stream.read(&mut buf)?;
    Ok(String::from_utf8_lossy(&buf[..n]).to_string())
}

fn cmd(parts: &[&str]) -> Vec<String> {
    parts.iter().map(|part| (*part).to_string()).collect()
}

fn now_ms() -> String {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .to_string()
}

fn usage() -> ! {
    eprintln!(
        "usage:
  a9-gateway init
  a9-gateway submit <task_id> <prompt>
  a9-gateway lease [consumer]
  a9-gateway ack <stream_id>
  a9-gateway fail <stream_id> <reason>
  a9-gateway heartbeat [worker_id]
  a9-gateway status"
    );
    std::process::exit(2);
}

fn main() -> std::io::Result<()> {
    let addr = env::var("A9_REDIS_ADDR").unwrap_or_else(|_| "127.0.0.1:63799".to_string());
    let args: Vec<String> = env::args().collect();
    let Some(command) = args.get(1).map(String::as_str) else {
        usage();
    };

    match command {
        "init" => {
            for stream in [TASK_STREAM, EVENT_STREAM, "a9:deep_marks", HEARTBEAT_STREAM] {
                let out = redis_roundtrip(
                    &addr,
                    &cmd(&["XGROUP", "CREATE", stream, WORKER_GROUP, "$", "MKSTREAM"]),
                )?;
                println!("{stream}: {}", out.trim());
            }
        }
        "submit" => {
            if args.len() < 4 {
                usage();
            }
            let task_id = &args[2];
            let prompt = &args[3];
            let created_at = now_ms();
            let out = redis_roundtrip(
                &addr,
                &[
                    "XADD".into(),
                    TASK_STREAM.into(),
                    "*".into(),
                    "task_id".into(),
                    task_id.into(),
                    "prompt".into(),
                    prompt.into(),
                    "created_at_ms".into(),
                    created_at,
                    "status".into(),
                    "queued".into(),
                ],
            )?;
            println!("{}", out.trim());
        }
        "lease" => {
            let consumer = args.get(2).map(String::as_str).unwrap_or("a9-gateway");
            let out = redis_roundtrip(
                &addr,
                &cmd(&[
                    "XREADGROUP",
                    "GROUP",
                    WORKER_GROUP,
                    consumer,
                    "COUNT",
                    "1",
                    "BLOCK",
                    "1000",
                    "STREAMS",
                    TASK_STREAM,
                    ">",
                ]),
            )?;
            println!("{}", out.trim());
        }
        "ack" => {
            let Some(stream_id) = args.get(2) else {
                usage();
            };
            let out = redis_roundtrip(
                &addr,
                &cmd(&["XACK", TASK_STREAM, WORKER_GROUP, stream_id.as_str()]),
            )?;
            println!("{}", out.trim());
        }
        "fail" => {
            if args.len() < 4 {
                usage();
            }
            let stream_id = &args[2];
            let reason = &args[3];
            let out = redis_roundtrip(
                &addr,
                &[
                    "XADD".into(),
                    EVENT_STREAM.into(),
                    "*".into(),
                    "type".into(),
                    "task_failed".into(),
                    "stream_id".into(),
                    stream_id.into(),
                    "reason".into(),
                    reason.into(),
                    "created_at_ms".into(),
                    now_ms(),
                ],
            )?;
            println!("{}", out.trim());
        }
        "heartbeat" => {
            let worker_id = args.get(2).map(String::as_str).unwrap_or("a9-gateway");
            let heartbeat_id = redis_roundtrip(
                &addr,
                &[
                    "XADD".into(),
                    HEARTBEAT_STREAM.into(),
                    "*".into(),
                    "worker_id".into(),
                    worker_id.into(),
                    "created_at_ms".into(),
                    now_ms(),
                ],
            )?;
            let ts = redis_roundtrip(
                &addr,
                &cmd(&["TS.ADD", "a9:ts:heartbeat", "*", "1"]),
            )?;
            println!("stream={}", heartbeat_id.trim());
            println!("timeseries={}", ts.trim());
        }
        "status" => {
            for parts in [
                cmd(&["XLEN", TASK_STREAM]),
                cmd(&["XLEN", EVENT_STREAM]),
                cmd(&["XLEN", "a9:deep_marks"]),
                cmd(&["XLEN", HEARTBEAT_STREAM]),
                cmd(&["XINFO", "GROUPS", TASK_STREAM]),
                cmd(&["FUNCTION", "LIST"]),
            ] {
                println!("{}", redis_roundtrip(&addr, &parts)?.replace("\r\n", " ").trim());
            }
        }
        _ => usage(),
    }

    Ok(())
}
