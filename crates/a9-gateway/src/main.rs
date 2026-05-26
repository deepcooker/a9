use std::env;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const TASK_STREAM: &str = "a9:tasks";
const EVENT_STREAM: &str = "a9:events";
const HEARTBEAT_STREAM: &str = "a9:heartbeats";
const WORKER_GROUP: &str = "a9-workers";

trait ReconnectBackoff {
    fn delay(&self, attempt: u32) -> Duration;
}

struct DefaultReconnectBackoff;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RedisFailureKind {
    Retryable,
    Terminal,
}

impl RedisFailureKind {
    fn is_retryable(&self) -> bool {
        matches!(self, RedisFailureKind::Retryable)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ReconnectLifecycleEvent {
    AttemptStarted { attempt: u32 },
    RetryScheduled { attempt: u32, delay_ms: u64 },
    FailureClassified {
        attempt: u32,
        kind: RedisFailureKind,
        error_kind: std::io::ErrorKind,
    },
    AttemptSucceeded { attempt: u32 },
    ExhaustedRetries { max_retries: u32 },
}

impl DefaultReconnectBackoff {
    fn classify_failure(error: &std::io::Error) -> RedisFailureKind {
        match error.kind() {
            std::io::ErrorKind::TimedOut
            | std::io::ErrorKind::Interrupted
            | std::io::ErrorKind::NotConnected
            | std::io::ErrorKind::ConnectionRefused
            | std::io::ErrorKind::ConnectionReset
            | std::io::ErrorKind::ConnectionAborted => RedisFailureKind::Retryable,
            std::io::ErrorKind::InvalidInput
            | std::io::ErrorKind::PermissionDenied
            | std::io::ErrorKind::InvalidData
            | std::io::ErrorKind::Unsupported => RedisFailureKind::Terminal,
            _ => RedisFailureKind::Terminal,
        }
    }
}

impl ReconnectBackoff for DefaultReconnectBackoff {
    fn delay(&self, attempt: u32) -> Duration {
        match attempt {
            0 => Duration::ZERO,
            n => Duration::from_millis((125u64 * 2u64.pow((n - 1).min(31))).min(60_000)),
        }
    }
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

fn redis_roundtrip_once(addr: &str, parts: &[String]) -> std::io::Result<String> {
    let mut stream = TcpStream::connect(addr)?;
    stream.set_read_timeout(Some(Duration::from_secs(3)))?;
    stream.set_write_timeout(Some(Duration::from_secs(3)))?;
    stream.write_all(&encode_command(parts))?;
    let mut buf = vec![0; 65536];
    let n = stream.read(&mut buf)?;
    Ok(String::from_utf8_lossy(&buf[..n]).to_string())
}

fn redis_roundtrip_with_retries<B: ReconnectBackoff>(
    attempt: impl FnMut() -> std::io::Result<String>,
    backoff: &B,
    max_retries: u32,
) -> std::io::Result<String> {
    redis_roundtrip_with_retries_observer(attempt, backoff, max_retries, |_| {})
}

fn redis_roundtrip_with_retries_observer<B: ReconnectBackoff>(
    mut attempt: impl FnMut() -> std::io::Result<String>,
    backoff: &B,
    max_retries: u32,
    mut on_event: impl FnMut(ReconnectLifecycleEvent),
) -> std::io::Result<String> {
    let mut last_error = None;
    for retry in 0..=max_retries {
        on_event(ReconnectLifecycleEvent::AttemptStarted { attempt: retry });
        if retry > 0 {
            let delay = backoff.delay(retry);
            on_event(ReconnectLifecycleEvent::RetryScheduled {
                attempt: retry,
                delay_ms: delay.as_millis() as u64,
            });
            thread::sleep(delay);
        }
        match attempt() {
            Ok(response) => {
                on_event(ReconnectLifecycleEvent::AttemptSucceeded { attempt: retry });
                return Ok(response);
            }
            Err(error) => {
                let failure = DefaultReconnectBackoff::classify_failure(&error);
                on_event(ReconnectLifecycleEvent::FailureClassified {
                    attempt: retry,
                    kind: failure,
                    error_kind: error.kind(),
                });
                if !failure.is_retryable() {
                    return Err(error);
                }
                last_error = Some(error);
            }
        }
    }
    on_event(ReconnectLifecycleEvent::ExhaustedRetries { max_retries });
    Err(last_error.unwrap_or_else(|| {
        std::io::Error::new(std::io::ErrorKind::Other, "redis roundtrip failed")
    }))
}

fn redis_roundtrip(addr: &str, parts: &[String]) -> std::io::Result<String> {
    let retries = env::var("A9_REDIS_RETRIES")
        .ok()
        .and_then(|value| value.parse::<u32>().ok())
        .unwrap_or(3);
    redis_roundtrip_with_retries(
        || redis_roundtrip_once(addr, parts),
        &DefaultReconnectBackoff,
        retries,
    )
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;
    use std::io::ErrorKind;

    #[derive(Default)]
    struct NoopBackoff;

    impl ReconnectBackoff for NoopBackoff {
        fn delay(&self, _attempt: u32) -> Duration {
            Duration::ZERO
        }
    }

    #[test]
    fn backoff_first_attempt_is_immediate() {
        let backoff = DefaultReconnectBackoff;
        assert_eq!(backoff.delay(0), Duration::ZERO);
    }

    #[test]
    fn backoff_is_exponential_with_small_constant_delay() {
        let backoff = DefaultReconnectBackoff;
        assert_eq!(backoff.delay(1), Duration::from_millis(125));
        assert_eq!(backoff.delay(2), Duration::from_millis(250));
        assert_eq!(backoff.delay(3), Duration::from_millis(500));
    }

    #[test]
    fn backoff_is_capped_at_barter_rs_style_exponent() {
        let backoff = DefaultReconnectBackoff;
        assert_eq!(backoff.delay(10), Duration::from_millis(60000));
        assert_eq!(backoff.delay(99), Duration::from_millis(60000));
    }

    #[test]
    fn classify_failure_marks_retryable_kinds() {
        assert_eq!(
            DefaultReconnectBackoff::classify_failure(&std::io::Error::new(
                ErrorKind::TimedOut,
                "timeout"
            )),
            RedisFailureKind::Retryable
        );
        assert_eq!(
            DefaultReconnectBackoff::classify_failure(&std::io::Error::new(
                ErrorKind::Interrupted,
                "interrupted"
            )),
            RedisFailureKind::Retryable
        );
    }

    #[test]
    fn classify_failure_marks_terminal_kinds() {
        assert_eq!(
            DefaultReconnectBackoff::classify_failure(&std::io::Error::new(
                ErrorKind::InvalidInput,
                "invalid input"
            )),
            RedisFailureKind::Terminal
        );
        assert_eq!(
            DefaultReconnectBackoff::classify_failure(&std::io::Error::new(
                ErrorKind::PermissionDenied,
                "permission denied"
            )),
            RedisFailureKind::Terminal
        );
    }

    #[test]
    fn retry_policy_stops_after_terminal_failures() {
        let attempts = Cell::new(0);
        let result = redis_roundtrip_with_retries(
            || {
                attempts.set(attempts.get() + 1);
                Err(std::io::Error::new(
                    ErrorKind::PermissionDenied,
                    "permission denied",
                ))
            },
            &NoopBackoff,
            3,
        );

        assert!(result.is_err());
        assert_eq!(attempts.get(), 1);
    }

    #[test]
    fn retry_policy_keeps_retrying_retryable_failures() {
        let attempts = Cell::new(0);
        let result = redis_roundtrip_with_retries(
            || {
                let next = attempts.get() + 1;
                attempts.set(next);
                if next < 3 {
                    Err(std::io::Error::new(ErrorKind::TimedOut, "timeout"))
                } else {
                    Ok("ok".to_string())
                }
            },
            &NoopBackoff,
            5,
        );

        assert_eq!(result.unwrap(), "ok");
        assert_eq!(attempts.get(), 3);
    }

    #[test]
    fn retry_policy_emits_typed_lifecycle_events() {
        let attempts = Cell::new(0);
        let mut events = Vec::new();
        let result = redis_roundtrip_with_retries_observer(
            || {
                let next = attempts.get() + 1;
                attempts.set(next);
                if next == 1 {
                    Err(std::io::Error::new(ErrorKind::TimedOut, "timeout"))
                } else {
                    Ok("ok".to_string())
                }
            },
            &NoopBackoff,
            3,
            |event| events.push(event),
        );

        assert_eq!(result.unwrap(), "ok");
        assert_eq!(
            events,
            vec![
                ReconnectLifecycleEvent::AttemptStarted { attempt: 0 },
                ReconnectLifecycleEvent::FailureClassified {
                    attempt: 0,
                    kind: RedisFailureKind::Retryable,
                    error_kind: ErrorKind::TimedOut,
                },
                ReconnectLifecycleEvent::AttemptStarted { attempt: 1 },
                ReconnectLifecycleEvent::RetryScheduled {
                    attempt: 1,
                    delay_ms: 0,
                },
                ReconnectLifecycleEvent::AttemptSucceeded { attempt: 1 },
            ]
        );
    }
}
