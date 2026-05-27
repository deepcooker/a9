use std::env;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::sync::mpsc::{Receiver, SyncSender, TryRecvError, TrySendError};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const TASK_STREAM: &str = "a9:tasks";
const EVENT_STREAM: &str = "a9:events";
const HEARTBEAT_STREAM: &str = "a9:heartbeats";
const WORKER_GROUP: &str = "a9-workers";
const CONTROL_CHANNEL_CAPACITY: usize = 128;
const OVERLOADED_ERROR_CODE: i64 = -32001;
const OVERLOADED_ERROR_MESSAGE: &str = "Server overloaded; retry later.";

trait ReconnectBackoff {
    fn delay(&self, attempt: u32) -> Duration;
}

struct DefaultReconnectBackoff;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RedisFailureKind {
    Retryable,
    Terminal,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ConnectErrorAction {
    Reconnect,
    Terminate,
}

impl ConnectErrorAction {
    fn as_str(&self) -> &'static str {
        match self {
            ConnectErrorAction::Reconnect => "reconnect",
            ConnectErrorAction::Terminate => "terminate",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum StreamErrorAction {
    Continue,
    Reconnect,
}

impl StreamErrorAction {
    fn as_str(&self) -> &'static str {
        match self {
            StreamErrorAction::Continue => "continue",
            StreamErrorAction::Reconnect => "reconnect",
        }
    }
}

impl RedisFailureKind {
    fn is_retryable(&self) -> bool {
        matches!(self, RedisFailureKind::Retryable)
    }

    fn error_class(&self, kind: std::io::ErrorKind) -> &'static str {
        match kind {
            std::io::ErrorKind::TimedOut => "timeout",
            std::io::ErrorKind::InvalidData | std::io::ErrorKind::Unsupported => "protocol",
            std::io::ErrorKind::PermissionDenied => "auth",
            std::io::ErrorKind::ConnectionRefused
            | std::io::ErrorKind::ConnectionReset
            | std::io::ErrorKind::ConnectionAborted
            | std::io::ErrorKind::NotConnected
            | std::io::ErrorKind::Interrupted => "io",
            _ => "unknown",
        }
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

#[derive(Debug, Clone, PartialEq, Eq)]
struct GatewayReconnectDecision {
    phase: &'static str,
    action: &'static str,
    error_class: &'static str,
    attempt: u32,
    delay_ms: u64,
    policy_budget_remaining: u32,
    origin: &'static str,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct GatewayConnectionId(u64);

#[derive(Debug, Clone, PartialEq, Eq)]
enum GatewayIncomingMessage {
    Request { id: u64, method: String },
    Response { id: u64, result: String },
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum GatewayTransportEvent {
    IncomingMessage {
        connection_id: GatewayConnectionId,
        message: GatewayIncomingMessage,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum GatewayOutgoingMessage {
    OverloadedError { request_id: u64, code: i64, message: &'static str },
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct GatewayTransportContractReport {
    capacity: usize,
    overload_error_code: i64,
    request_overload_returns_retry_error: bool,
    response_waits_on_backpressure: bool,
    writer_full_preserves_existing_message: bool,
}

fn gateway_channel_capacity() -> usize {
    CONTROL_CHANNEL_CAPACITY
}

fn forward_incoming_gateway_message(
    transport_tx: &SyncSender<GatewayTransportEvent>,
    writer_tx: &SyncSender<GatewayOutgoingMessage>,
    connection_id: GatewayConnectionId,
    message: GatewayIncomingMessage,
) -> bool {
    let event = GatewayTransportEvent::IncomingMessage {
        connection_id,
        message,
    };
    match transport_tx.try_send(event) {
        Ok(()) => true,
        Err(TrySendError::Disconnected(_)) => false,
        Err(TrySendError::Full(event)) => match event {
            GatewayTransportEvent::IncomingMessage {
                message: GatewayIncomingMessage::Request { id, .. },
                ..
            } => {
                let _ = writer_tx.try_send(GatewayOutgoingMessage::OverloadedError {
                    request_id: id,
                    code: OVERLOADED_ERROR_CODE,
                    message: OVERLOADED_ERROR_MESSAGE,
                });
                true
            }
            GatewayTransportEvent::IncomingMessage { .. } => transport_tx.send(event).is_ok(),
        },
    }
}

fn recv_gateway_event(receiver: &Receiver<GatewayTransportEvent>) -> Option<GatewayTransportEvent> {
    match receiver.try_recv() {
        Ok(event) => Some(event),
        Err(TryRecvError::Empty) | Err(TryRecvError::Disconnected) => None,
    }
}

fn gateway_transport_contract_report() -> GatewayTransportContractReport {
    GatewayTransportContractReport {
        capacity: gateway_channel_capacity(),
        overload_error_code: OVERLOADED_ERROR_CODE,
        request_overload_returns_retry_error: request_overload_returns_retry_error(),
        response_waits_on_backpressure: response_waits_on_backpressure(),
        writer_full_preserves_existing_message: writer_full_preserves_existing_message(),
    }
}

fn request_overload_returns_retry_error() -> bool {
    let (transport_tx, transport_rx) = std::sync::mpsc::sync_channel(1);
    let (writer_tx, writer_rx) = std::sync::mpsc::sync_channel(1);
    if transport_tx
        .send(GatewayTransportEvent::IncomingMessage {
            connection_id: GatewayConnectionId(7),
            message: GatewayIncomingMessage::Response {
                id: 1,
                result: "queued".to_string(),
            },
        })
        .is_err()
    {
        return false;
    }
    let forwarded = forward_incoming_gateway_message(
        &transport_tx,
        &writer_tx,
        GatewayConnectionId(7),
        GatewayIncomingMessage::Request {
            id: 99,
            method: "submit".to_string(),
        },
    );
    let overload = writer_rx.try_recv().ok();
    let seeded_event_still_queued = matches!(
        recv_gateway_event(&transport_rx),
        Some(GatewayTransportEvent::IncomingMessage {
            message: GatewayIncomingMessage::Response { id: 1, .. },
            ..
        })
    );
    forwarded
        && seeded_event_still_queued
        && overload
            == Some(GatewayOutgoingMessage::OverloadedError {
                request_id: 99,
                code: OVERLOADED_ERROR_CODE,
                message: OVERLOADED_ERROR_MESSAGE,
            })
}

fn response_waits_on_backpressure() -> bool {
    let (transport_tx, transport_rx) = std::sync::mpsc::sync_channel(1);
    let (writer_tx, writer_rx) = std::sync::mpsc::sync_channel(1);
    if transport_tx
        .send(GatewayTransportEvent::IncomingMessage {
            connection_id: GatewayConnectionId(3),
            message: GatewayIncomingMessage::Request {
                id: 1,
                method: "queued".to_string(),
            },
        })
        .is_err()
    {
        return false;
    }
    let handle = thread::spawn(move || {
        forward_incoming_gateway_message(
            &transport_tx,
            &writer_tx,
            GatewayConnectionId(3),
            GatewayIncomingMessage::Response {
                id: 2,
                result: "ok".to_string(),
            },
        )
    });
    thread::sleep(Duration::from_millis(25));
    let no_overload = writer_rx.try_recv().is_err();
    let first = recv_gateway_event(&transport_rx);
    let first_was_seeded = matches!(
        first,
        Some(GatewayTransportEvent::IncomingMessage {
            message: GatewayIncomingMessage::Request { id: 1, .. },
            ..
        })
    );
    let joined = handle.join().unwrap_or(false);
    let second_was_response = matches!(
        recv_gateway_event(&transport_rx),
        Some(GatewayTransportEvent::IncomingMessage {
            message: GatewayIncomingMessage::Response { id: 2, .. },
            ..
        })
    );
    no_overload && first_was_seeded && joined && second_was_response
}

fn writer_full_preserves_existing_message() -> bool {
    let (transport_tx, _transport_rx) = std::sync::mpsc::sync_channel(1);
    let (writer_tx, writer_rx) = std::sync::mpsc::sync_channel(1);
    if transport_tx
        .send(GatewayTransportEvent::IncomingMessage {
            connection_id: GatewayConnectionId(4),
            message: GatewayIncomingMessage::Response {
                id: 1,
                result: "queued".to_string(),
            },
        })
        .is_err()
    {
        return false;
    }
    let original = GatewayOutgoingMessage::OverloadedError {
        request_id: 1,
        code: OVERLOADED_ERROR_CODE,
        message: OVERLOADED_ERROR_MESSAGE,
    };
    if writer_tx.send(original.clone()).is_err() {
        return false;
    }
    let forwarded = forward_incoming_gateway_message(
        &transport_tx,
        &writer_tx,
        GatewayConnectionId(4),
        GatewayIncomingMessage::Request {
            id: 2,
            method: "submit".to_string(),
        },
    );
    forwarded && writer_rx.try_recv().ok() == Some(original) && writer_rx.try_recv().is_err()
}

fn print_transport_contract_report(report: GatewayTransportContractReport) {
    println!(
        "{{\"status\":\"ok\",\"kind\":\"gateway_transport_contract\",\"capacity\":{},\"overload_error_code\":{},\"request_overload_returns_retry_error\":{},\"response_waits_on_backpressure\":{},\"writer_full_preserves_existing_message\":{}}}",
        report.capacity,
        report.overload_error_code,
        report.request_overload_returns_retry_error,
        report.response_waits_on_backpressure,
        report.writer_full_preserves_existing_message
    );
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

#[cfg(test)]
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
    redis_roundtrip_with_retries_observer(
        || redis_roundtrip_once(addr, parts),
        &DefaultReconnectBackoff,
        retries,
        |event| emit_decision_evidence(addr, retries, event),
    )
}

fn connect_error_action(kind: RedisFailureKind, attempt: u32, max_retries: u32) -> ConnectErrorAction {
    if kind.is_retryable() && attempt < max_retries {
        ConnectErrorAction::Reconnect
    } else {
        ConnectErrorAction::Terminate
    }
}

fn stream_error_action(kind: RedisFailureKind) -> StreamErrorAction {
    if kind.is_retryable() {
        StreamErrorAction::Continue
    } else {
        StreamErrorAction::Reconnect
    }
}

fn emit_decision_evidence(addr: &str, max_retries: u32, event: ReconnectLifecycleEvent) {
    for decision in decisions_from_lifecycle_event(max_retries, event) {
        emit_gateway_decision(
            addr,
            decision.phase,
            decision.action,
            decision.error_class,
            decision.attempt,
            decision.delay_ms,
            decision.policy_budget_remaining,
            decision.origin,
        );
    }
}

fn decisions_from_lifecycle_event(
    max_retries: u32,
    event: ReconnectLifecycleEvent,
) -> Vec<GatewayReconnectDecision> {
    match event {
        ReconnectLifecycleEvent::FailureClassified {
            attempt,
            kind,
            error_kind,
        } => {
            let action = connect_error_action(kind, attempt, max_retries);
            let delay_ms = if action == ConnectErrorAction::Reconnect {
                DefaultReconnectBackoff.delay(attempt + 1).as_millis() as u64
            } else {
                0
            };
            let mut decisions = Vec::with_capacity(2);
            decisions.push(GatewayReconnectDecision {
                phase: "connect",
                action: action.as_str(),
                error_class: kind.error_class(error_kind),
                attempt,
                delay_ms,
                policy_budget_remaining: max_retries.saturating_sub(attempt),
                origin: "connect_error",
            });
            let stream_action = stream_error_action(kind);
            decisions.push(GatewayReconnectDecision {
                phase: "stream",
                action: stream_action.as_str(),
                error_class: kind.error_class(error_kind),
                attempt,
                delay_ms: 0,
                policy_budget_remaining: max_retries.saturating_sub(attempt),
                origin: "stream_error",
            });
            decisions
        }
        ReconnectLifecycleEvent::RetryScheduled { attempt, delay_ms } => {
            vec![GatewayReconnectDecision {
                phase: "connect",
                action: ConnectErrorAction::Reconnect.as_str(),
                error_class: "unknown",
                attempt,
                delay_ms,
                policy_budget_remaining: max_retries.saturating_sub(attempt),
                origin: "connect_error",
            }]
        }
        ReconnectLifecycleEvent::ExhaustedRetries { max_retries } => {
            vec![GatewayReconnectDecision {
                phase: "connect",
                action: ConnectErrorAction::Terminate.as_str(),
                error_class: "unknown",
                attempt: max_retries,
                delay_ms: 0,
                policy_budget_remaining: 0,
                origin: "connect_error",
            }]
        }
        ReconnectLifecycleEvent::AttemptStarted { .. } | ReconnectLifecycleEvent::AttemptSucceeded { .. } => {
            Vec::new()
        }
    }
}

fn emit_gateway_decision(
    addr: &str,
    phase: &str,
    action: &str,
    error_class: &str,
    attempt: u32,
    delay_ms: u64,
    policy_budget_remaining: u32,
    origin: &str,
) {
    let _ = redis_roundtrip_once(
        addr,
        &[
            "XADD".to_string(),
            EVENT_STREAM.to_string(),
            "*".to_string(),
            "type".to_string(),
            "gateway_reconnect_decision".to_string(),
            "kind".to_string(),
            "gateway_reconnect_decision".to_string(),
            "phase".to_string(),
            phase.to_string(),
            "action".to_string(),
            action.to_string(),
            "error_class".to_string(),
            error_class.to_string(),
            "attempt".to_string(),
            attempt.to_string(),
            "delay_ms".to_string(),
            delay_ms.to_string(),
            "policy_budget_remaining".to_string(),
            policy_budget_remaining.to_string(),
            "origin".to_string(),
            origin.to_string(),
            "ts".to_string(),
            now_ms(),
        ],
    );
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
  a9-gateway status
  a9-gateway transport-contract"
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
        "transport-contract" => {
            print_transport_contract_report(gateway_transport_contract_report());
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
    use std::net::TcpListener;
    use std::sync::mpsc;

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
    fn retry_policy_terminal_stop_path_emits_no_retry_scheduled_event() {
        let attempts = Cell::new(0);
        let mut events = Vec::new();
        let result = redis_roundtrip_with_retries_observer(
            || {
                attempts.set(attempts.get() + 1);
                Err(std::io::Error::new(
                    ErrorKind::PermissionDenied,
                    "permission denied",
                ))
            },
            &NoopBackoff,
            3,
            |event| events.push(event),
        );

        assert!(result.is_err());
        assert_eq!(attempts.get(), 1);
        assert!(events
            .iter()
            .any(|event| matches!(event, ReconnectLifecycleEvent::FailureClassified { kind: RedisFailureKind::Terminal, .. })));
        assert!(
            !events
                .iter()
                .any(|event| matches!(event, ReconnectLifecycleEvent::RetryScheduled { .. })),
            "terminal stop-path must not emit retry-scheduled lifecycle events"
        );
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

    #[test]
    fn retry_policy_emits_exhausted_and_returns_last_retryable_error() {
        let attempts = Cell::new(0);
        let mut events = Vec::new();
        let result = redis_roundtrip_with_retries_observer(
            || {
                let next = attempts.get() + 1;
                attempts.set(next);
                Err(std::io::Error::new(
                    ErrorKind::TimedOut,
                    format!("timeout-{next}"),
                ))
            },
            &NoopBackoff,
            2,
            |event| events.push(event),
        );

        assert!(result.is_err());
        let err = result.err().expect("error expected after exhausting retries");
        assert_eq!(err.kind(), ErrorKind::TimedOut);
        assert_eq!(err.to_string(), "timeout-3");
        assert_eq!(attempts.get(), 3);
        assert!(matches!(
            events.last(),
            Some(ReconnectLifecycleEvent::ExhaustedRetries { max_retries: 2 })
        ));
    }

    #[test]
    fn connect_action_contract_is_typed() {
        assert_eq!(
            connect_error_action(RedisFailureKind::Retryable, 0, 3),
            ConnectErrorAction::Reconnect
        );
        assert_eq!(
            connect_error_action(RedisFailureKind::Retryable, 3, 3),
            ConnectErrorAction::Terminate
        );
        assert_eq!(
            connect_error_action(RedisFailureKind::Terminal, 0, 3),
            ConnectErrorAction::Terminate
        );
    }

    #[test]
    fn stream_action_contract_is_typed() {
        assert_eq!(
            stream_error_action(RedisFailureKind::Retryable),
            StreamErrorAction::Continue
        );
        assert_eq!(
            stream_error_action(RedisFailureKind::Terminal),
            StreamErrorAction::Reconnect
        );
    }

    #[test]
    fn codex_style_gateway_capacity_is_explicit() {
        assert_eq!(gateway_channel_capacity(), 128);
    }

    #[test]
    fn transport_contract_report_runs_all_backpressure_checks() {
        assert_eq!(
            gateway_transport_contract_report(),
            GatewayTransportContractReport {
                capacity: 128,
                overload_error_code: -32001,
                request_overload_returns_retry_error: true,
                response_waits_on_backpressure: true,
                writer_full_preserves_existing_message: true,
            }
        );
    }

    #[test]
    fn incoming_request_overload_returns_retry_error_without_blocking() {
        let (transport_tx, transport_rx) = mpsc::sync_channel(1);
        let (writer_tx, writer_rx) = mpsc::sync_channel(1);
        transport_tx
            .send(GatewayTransportEvent::IncomingMessage {
                connection_id: GatewayConnectionId(7),
                message: GatewayIncomingMessage::Response {
                    id: 1,
                    result: "queued".to_string(),
                },
            })
            .expect("seed full inbound queue");

        let forwarded = forward_incoming_gateway_message(
            &transport_tx,
            &writer_tx,
            GatewayConnectionId(7),
            GatewayIncomingMessage::Request {
                id: 99,
                method: "submit".to_string(),
            },
        );

        assert!(forwarded);
        assert_eq!(
            writer_rx.try_recv().expect("overload response is queued"),
            GatewayOutgoingMessage::OverloadedError {
                request_id: 99,
                code: OVERLOADED_ERROR_CODE,
                message: OVERLOADED_ERROR_MESSAGE,
            }
        );
        assert!(matches!(
            recv_gateway_event(&transport_rx),
            Some(GatewayTransportEvent::IncomingMessage {
                message: GatewayIncomingMessage::Response { id: 1, .. },
                ..
            })
        ));
    }

    #[test]
    fn incoming_response_waits_on_backpressure_until_inbound_queue_drains() {
        let (transport_tx, transport_rx) = mpsc::sync_channel(1);
        let (writer_tx, writer_rx) = mpsc::sync_channel(1);
        transport_tx
            .send(GatewayTransportEvent::IncomingMessage {
                connection_id: GatewayConnectionId(3),
                message: GatewayIncomingMessage::Request {
                    id: 1,
                    method: "queued".to_string(),
                },
            })
            .expect("seed full inbound queue");

        let handle = thread::spawn(move || {
            forward_incoming_gateway_message(
                &transport_tx,
                &writer_tx,
                GatewayConnectionId(3),
                GatewayIncomingMessage::Response {
                    id: 2,
                    result: "ok".to_string(),
                },
            )
        });
        thread::sleep(Duration::from_millis(25));
        assert!(writer_rx.try_recv().is_err(), "responses should not emit overload errors");
        assert!(matches!(
            recv_gateway_event(&transport_rx),
            Some(GatewayTransportEvent::IncomingMessage {
                message: GatewayIncomingMessage::Request { id: 1, .. },
                ..
            })
        ));

        assert!(handle.join().expect("response sender exits after queue drains"));
        assert!(matches!(
            recv_gateway_event(&transport_rx),
            Some(GatewayTransportEvent::IncomingMessage {
                message: GatewayIncomingMessage::Response { id: 2, .. },
                ..
            })
        ));
    }

    #[test]
    fn writer_full_drops_only_overload_feedback_and_preserves_writer_queue() {
        let (transport_tx, _transport_rx) = mpsc::sync_channel(1);
        let (writer_tx, writer_rx) = mpsc::sync_channel(1);
        transport_tx
            .send(GatewayTransportEvent::IncomingMessage {
                connection_id: GatewayConnectionId(4),
                message: GatewayIncomingMessage::Response {
                    id: 1,
                    result: "queued".to_string(),
                },
            })
            .expect("seed full inbound queue");
        writer_tx
            .send(GatewayOutgoingMessage::OverloadedError {
                request_id: 1,
                code: OVERLOADED_ERROR_CODE,
                message: OVERLOADED_ERROR_MESSAGE,
            })
            .expect("seed full writer queue");

        let forwarded = forward_incoming_gateway_message(
            &transport_tx,
            &writer_tx,
            GatewayConnectionId(4),
            GatewayIncomingMessage::Request {
                id: 2,
                method: "submit".to_string(),
            },
        );

        assert!(forwarded);
        assert_eq!(
            writer_rx.try_recv().expect("original writer message remains queued"),
            GatewayOutgoingMessage::OverloadedError {
                request_id: 1,
                code: OVERLOADED_ERROR_CODE,
                message: OVERLOADED_ERROR_MESSAGE,
            }
        );
        assert!(writer_rx.try_recv().is_err());
    }

    #[test]
    fn failure_kind_maps_to_machine_error_classes() {
        assert_eq!(
            RedisFailureKind::Retryable.error_class(ErrorKind::TimedOut),
            "timeout"
        );
        assert_eq!(
            RedisFailureKind::Terminal.error_class(ErrorKind::PermissionDenied),
            "auth"
        );
        assert_eq!(
            RedisFailureKind::Terminal.error_class(ErrorKind::InvalidData),
            "protocol"
        );
    }

    #[test]
    fn decision_events_preserve_connect_and_stream_action_domains_for_retryable_failures() {
        let decisions = decisions_from_lifecycle_event(
            3,
            ReconnectLifecycleEvent::FailureClassified {
                attempt: 0,
                kind: RedisFailureKind::Retryable,
                error_kind: ErrorKind::TimedOut,
            },
        );

        assert_eq!(decisions.len(), 2);
        assert_eq!(decisions[0].phase, "connect");
        assert_eq!(decisions[0].action, ConnectErrorAction::Reconnect.as_str());
        assert_eq!(decisions[1].phase, "stream");
        assert_eq!(decisions[1].action, StreamErrorAction::Continue.as_str());
    }

    #[test]
    fn decision_events_preserve_connect_and_stream_action_domains_for_terminal_failures() {
        let decisions = decisions_from_lifecycle_event(
            3,
            ReconnectLifecycleEvent::FailureClassified {
                attempt: 0,
                kind: RedisFailureKind::Terminal,
                error_kind: ErrorKind::PermissionDenied,
            },
        );

        assert_eq!(decisions.len(), 2);
        assert_eq!(decisions[0].phase, "connect");
        assert_eq!(decisions[0].action, ConnectErrorAction::Terminate.as_str());
        assert_eq!(decisions[1].phase, "stream");
        assert_eq!(decisions[1].action, StreamErrorAction::Reconnect.as_str());
    }

    fn parse_resp_array(input: &[u8]) -> Option<Vec<String>> {
        if input.first().copied()? != b'*' {
            return None;
        }
        let mut idx = 1usize;
        let count_end = input[idx..].windows(2).position(|w| w == b"\r\n")? + idx;
        let count = std::str::from_utf8(&input[idx..count_end]).ok()?.parse::<usize>().ok()?;
        idx = count_end + 2;
        let mut parts = Vec::with_capacity(count);
        for _ in 0..count {
            if input.get(idx).copied()? != b'$' {
                return None;
            }
            idx += 1;
            let len_end = input[idx..].windows(2).position(|w| w == b"\r\n")? + idx;
            let len = std::str::from_utf8(&input[idx..len_end]).ok()?.parse::<usize>().ok()?;
            idx = len_end + 2;
            let part_end = idx.checked_add(len)?;
            let part = std::str::from_utf8(input.get(idx..part_end)?).ok()?.to_string();
            parts.push(part);
            idx = part_end;
            if input.get(idx..idx + 2)? != b"\r\n" {
                return None;
            }
            idx += 2;
        }
        Some(parts)
    }

    fn field<'a>(parts: &'a [String], key: &str) -> Option<&'a str> {
        let mut i = 0usize;
        while i + 1 < parts.len() {
            if parts[i] == key {
                return Some(parts[i + 1].as_str());
            }
            i += 1;
        }
        None
    }

    #[test]
    fn transcript_preserves_failure_then_retry_order_and_typed_domains() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind fake redis listener");
        let addr = listener.local_addr().expect("listener addr");
        let (tx, rx) = mpsc::channel::<Vec<Vec<String>>>();
        let server = std::thread::spawn(move || {
            let mut captured = Vec::new();
            for _ in 0..3 {
                let (mut stream, _) = listener.accept().expect("accept fake redis client");
                let mut buf = [0u8; 4096];
                let n = stream.read(&mut buf).expect("read redis command");
                let parts = parse_resp_array(&buf[..n]).expect("parse RESP array command");
                captured.push(parts);
                stream.write_all(b"+OK\r\n").expect("reply +OK");
            }
            tx.send(captured).expect("send transcript");
        });

        let failure = decisions_from_lifecycle_event(
            3,
            ReconnectLifecycleEvent::FailureClassified {
                attempt: 0,
                kind: RedisFailureKind::Retryable,
                error_kind: ErrorKind::TimedOut,
            },
        );
        let retry = decisions_from_lifecycle_event(
            3,
            ReconnectLifecycleEvent::RetryScheduled {
                attempt: 1,
                delay_ms: 125,
            },
        );
        for decision in failure.into_iter().chain(retry.into_iter()) {
            emit_gateway_decision(
                &addr.to_string(),
                decision.phase,
                decision.action,
                decision.error_class,
                decision.attempt,
                decision.delay_ms,
                decision.policy_budget_remaining,
                decision.origin,
            );
        }

        server.join().expect("fake redis server exits");
        let transcript = rx.recv().expect("receive transcript");
        assert_eq!(transcript.len(), 3);

        assert_eq!(transcript[0][0], "XADD");
        assert_eq!(field(&transcript[0], "phase"), Some("connect"));
        assert_eq!(
            field(&transcript[0], "action"),
            Some(ConnectErrorAction::Reconnect.as_str())
        );
        assert_eq!(field(&transcript[0], "origin"), Some("connect_error"));
        assert_eq!(field(&transcript[0], "error_class"), Some("timeout"));

        assert_eq!(field(&transcript[1], "phase"), Some("stream"));
        assert_eq!(
            field(&transcript[1], "action"),
            Some(StreamErrorAction::Continue.as_str())
        );
        assert_eq!(field(&transcript[1], "origin"), Some("stream_error"));
        assert_eq!(field(&transcript[1], "error_class"), Some("timeout"));

        assert_eq!(field(&transcript[2], "phase"), Some("connect"));
        assert_eq!(
            field(&transcript[2], "action"),
            Some(ConnectErrorAction::Reconnect.as_str())
        );
        assert_eq!(field(&transcript[2], "origin"), Some("connect_error"));
        assert_eq!(field(&transcript[2], "error_class"), Some("unknown"));
    }

    #[test]
    fn transcript_preserves_terminal_failure_order_and_typed_domains() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind fake redis listener");
        let addr = listener.local_addr().expect("listener addr");
        let (tx, rx) = mpsc::channel::<Vec<Vec<String>>>();
        let server = std::thread::spawn(move || {
            let mut captured = Vec::new();
            for _ in 0..2 {
                let (mut stream, _) = listener.accept().expect("accept fake redis client");
                let mut buf = [0u8; 4096];
                let n = stream.read(&mut buf).expect("read redis command");
                let parts = parse_resp_array(&buf[..n]).expect("parse RESP array command");
                captured.push(parts);
                stream.write_all(b"+OK\r\n").expect("reply +OK");
            }
            tx.send(captured).expect("send transcript");
        });

        let terminal = decisions_from_lifecycle_event(
            3,
            ReconnectLifecycleEvent::FailureClassified {
                attempt: 0,
                kind: RedisFailureKind::Terminal,
                error_kind: ErrorKind::PermissionDenied,
            },
        );
        for decision in terminal {
            emit_gateway_decision(
                &addr.to_string(),
                decision.phase,
                decision.action,
                decision.error_class,
                decision.attempt,
                decision.delay_ms,
                decision.policy_budget_remaining,
                decision.origin,
            );
        }

        server.join().expect("fake redis server exits");
        let transcript = rx.recv().expect("receive transcript");
        assert_eq!(transcript.len(), 2);

        assert_eq!(transcript[0][0], "XADD");
        assert_eq!(field(&transcript[0], "phase"), Some("connect"));
        assert_eq!(
            field(&transcript[0], "action"),
            Some(ConnectErrorAction::Terminate.as_str())
        );
        assert_eq!(field(&transcript[0], "origin"), Some("connect_error"));
        assert_eq!(field(&transcript[0], "error_class"), Some("auth"));

        assert_eq!(field(&transcript[1], "phase"), Some("stream"));
        assert_eq!(
            field(&transcript[1], "action"),
            Some(StreamErrorAction::Reconnect.as_str())
        );
        assert_eq!(field(&transcript[1], "origin"), Some("stream_error"));
        assert_eq!(field(&transcript[1], "error_class"), Some("auth"));
    }
}
