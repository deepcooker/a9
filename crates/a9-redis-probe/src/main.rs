use std::env;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::time::Duration;

fn encode_command(parts: &[&str]) -> Vec<u8> {
    let mut out = format!("*{}\r\n", parts.len()).into_bytes();
    for part in parts {
        out.extend_from_slice(format!("${}\r\n", part.len()).as_bytes());
        out.extend_from_slice(part.as_bytes());
        out.extend_from_slice(b"\r\n");
    }
    out
}

fn redis_roundtrip(addr: &str, parts: &[&str]) -> std::io::Result<String> {
    let mut stream = TcpStream::connect(addr)?;
    stream.set_read_timeout(Some(Duration::from_secs(2)))?;
    stream.set_write_timeout(Some(Duration::from_secs(2)))?;
    stream.write_all(&encode_command(parts))?;
    let mut buf = vec![0; 8192];
    let n = stream.read(&mut buf)?;
    Ok(String::from_utf8_lossy(&buf[..n]).to_string())
}

fn main() -> std::io::Result<()> {
    let addr = env::var("A9_REDIS_ADDR").unwrap_or_else(|_| "127.0.0.1:63799".to_string());
    let ping = redis_roundtrip(&addr, &["PING"])?;
    if !ping.contains("PONG") {
        eprintln!("redis ping failed: {ping}");
        std::process::exit(1);
    }

    let indexes = redis_roundtrip(&addr, &["FT._LIST"])?;
    let functions = redis_roundtrip(&addr, &["FUNCTION", "LIST"])?;
    let groups = redis_roundtrip(&addr, &["XINFO", "GROUPS", "a9:tasks"])?;

    println!("redis_addr={addr}");
    println!("ping={}", ping.trim());
    println!("indexes={}", indexes.replace("\r\n", " ").trim());
    println!("functions={}", functions.replace("\r\n", " ").trim());
    println!("task_groups={}", groups.replace("\r\n", " ").trim());
    Ok(())
}
