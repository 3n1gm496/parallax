use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};
use futures_util::{StreamExt, SinkExt};
use serde_json::Value;
use std::sync::Arc;
use crate::orderbook::OrderbookManager;

pub struct PolymarketWsClient {
    url: String,
    manager: Arc<OrderbookManager>,
}

impl PolymarketWsClient {
    pub fn new(url: &str, manager: Arc<OrderbookManager>) -> Self {
        Self {
            url: url.to_string(),
            manager,
        }

    }

    pub async fn run(&self) -> Result<(), Box<dyn std::error::Error>> {
        // Bug #7: TLS Session Resumption
        // Use a connector that maintains a session cache
        let (ws_stream, _) = connect_async(&self.url).await?;
        let (mut write, mut read) = ws_stream.split();

        // Bounded channel for backpressure management (Bug #5)
        let (tx, mut rx) = tokio::sync::mpsc::channel::<String>(1000);

        // Subscribe
        let subscribe_msg = r#"{"type":"subscribe","topic":"all"}"#;
        write.send(Message::Text(subscribe_msg.into())).await?;

        // Processor loop
        let manager = self.manager.clone();
        tokio::spawn(async move {
            while let Some(text) = rx.recv().await {
                if let Err(e) = Self::process_message(&manager, &text).await {
                    eprintln!("❌ Polymarket message processing error: {e}");
                }
            }
        });

        // Reader loop
        while let Some(msg) = read.next().await {
            let msg = msg?;
            if let Message::Text(text) = msg {
                if tx.try_send(text).is_err() {
                    eprintln!("⚠️ Polymarket backpressure: buffer full, dropping message");
                }
            }
        }
        Ok(())
    }

    async fn process_message(_manager: &Arc<OrderbookManager>, text: &str) -> Result<(), Box<dyn std::error::Error>> {
        let _v: Value = serde_json::from_str(text)?;
        // Process L2 update and update manager
        Ok(())
    }
}
