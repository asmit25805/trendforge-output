use std::convert::Infallible;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::Context;
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use hyper::{header::AUTHORIZATION, Body, Request, Response, StatusCode};
use jsonwebtoken::{decode, Algorithm, DecodingKey, Validation, TokenData, errors::Error as JwtError};
use log::{error, info, warn};
use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;
use thiserror::Error;
use uuid::Uuid;

/// Claims embedded in the JWT.
#[derive(Debug, Serialize, Deserialize)]
struct Claims {
    sub: String,
    exp: usize,
    iat: usize,
    // Additional fields can be added as needed.
}

#[derive(Debug, Error)]
pub enum AuthError {
    #[error("missing authorization header")] MissingHeader,
    #[error("invalid token: {0}")] InvalidToken(#[from] JwtError),
    #[error("token expired")] Expired,
    #[error("internal error: {0}")] Internal(#[from] anyhow::Error),
}

/// Represents a validated user token.
#[derive(Debug, Clone)]
pub struct UserToken {
    pub user_id: Uuid,
    pub issued_at: DateTime<Utc>,
    pub expires_at: DateTime<Utc>,
}

/// Middleware that validates JWTs on incoming requests.
pub struct AuthMiddleware {
    decoding_key: DecodingKey,
    validation: Validation,
}

impl AuthMiddleware {
    /// Create a new middleware instance with the given HMAC secret.
    pub fn new(secret: &str) -> Self {
        let decoding_key = DecodingKey::from_secret(secret.as_bytes());
        let mut validation = Validation::new(Algorithm::HS256);
        validation.validate_exp = true;
        Self { decoding_key, validation }
    }

    /// Extract and validate the token from the request.
    pub async fn resolve_token(&self, req: &Request<Body>) -> Result<UserToken, AuthError> {
        let header = req.headers().get(AUTHORIZATION).ok_or(AuthError::MissingHeader)?;
        let auth_str = header.to_str().map_err(|_| AuthError::InvalidToken(JwtError::InvalidToken))?;
        let token = auth_str.trim_start_matches("Bearer ");
        let token_data: TokenData<Claims> = decode(token, &self.decoding_key, &self.validation)?;
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs() as usize;
        if token_data.claims.exp < now {
            return Err(AuthError::Expired);
        }
        let user_id = Uuid::parse_str(&token_data.claims.sub).map_err(|e| AuthError::Internal(e.into()))?;
        Ok(UserToken {
            user_id,
            issued_at: DateTime::<Utc>::from(SystemTime::UNIX_EPOCH + Duration::from_secs(token_data.claims.iat as u64)),
            expires_at: DateTime::<Utc>::from(SystemTime::UNIX_EPOCH + Duration::from_secs(token_data.claims.exp as u64)),
        })
    }
}

// Export the public symbols.
pub use AuthMiddleware;
pub use UserToken;
pub use resolve_token;
