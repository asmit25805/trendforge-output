use anyhow::Result;
use std::io::{self, Stdout};
use std::sync::Arc;
use std::time::Instant;

use crossterm::{
    execute,
    terminal::{disable_raw_mode, enable_raw_mode},
    event::{self, Event as CEvent, KeyCode, KeyEvent},
};
use ratatui::{
    backend::CrosstermBackend,
    layout::{Constraint, Direction, Layout},
    style::{Color, Modifier, Style},
    symbols,
    widgets::{Block, Borders, Paragraph, Widget},
    Terminal,
};

use crate::app_state::AppState;

/// Simple terminal UI that renders the current application state.
pub struct UI {
    terminal: Terminal<CrosstermBackend<Stdout>>,
    state: Arc<AppState>,
}

impl UI {
    /// Initialise the UI with the shared application state.
    pub fn new(state: Arc<AppState>) -> Result<Self> {
        enable_raw_mode()?;
        let stdout = io::stdout();
        let backend = CrosstermBackend::new(stdout);
        let terminal = Terminal::new(backend)?;
        Ok(Self { terminal, state })
    }

    /// Run the UI event loop until the user quits.
    pub async fn run(&mut self) -> Result<()> {
        loop {
            self.terminal.draw(|f| {
                let size = f.size();
                let block = Block::default()
                    .title("dnswatch")
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(Color::Cyan));
                f.render_widget(block, size);
            })?;

            // Simple event handling – quit on 'q' or Ctrl‑C.
            if crossterm::event::poll(std::time::Duration::from_millis(200))? {
                if let CEvent::Key(KeyEvent { code, .. }) = event::read()? {
                    match code {
                        KeyCode::Char('q') | KeyCode::Esc => break,
                        _ => {}
                    }
                }
            }
        }
        disable_raw_mode()?;
        Ok(())
    }
}
