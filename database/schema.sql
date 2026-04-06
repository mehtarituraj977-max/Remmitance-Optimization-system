-- ============================================================
-- StableBridge Cross-Border Remittance — PostgreSQL Schema
-- Supports multi-currency, multi-chain, double-entry ledger
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- USERS
-- ============================================================
CREATE TABLE users (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    external_id         VARCHAR(64) UNIQUE NOT NULL,
    email               VARCHAR(255) UNIQUE,
    phone               VARCHAR(20) UNIQUE,
    full_name_enc       BYTEA NOT NULL,
    date_of_birth_enc   BYTEA,
    nationality         CHAR(2),
    residence_country   CHAR(2) NOT NULL,

    kyc_tier            SMALLINT NOT NULL DEFAULT 0
                        CHECK (kyc_tier BETWEEN 0 AND 3),
    kyc_status          VARCHAR(20) NOT NULL DEFAULT 'PENDING'
                        CHECK (kyc_status IN (
                            'PENDING','IN_REVIEW','APPROVED','REJECTED','EXPIRED'
                        )),
    kyc_provider        VARCHAR(50),
    kyc_verified_at     TIMESTAMPTZ,
    kyc_expires_at      TIMESTAMPTZ,

    risk_score          SMALLINT DEFAULT 0 CHECK (risk_score BETWEEN 0 AND 100),
    pep_flag            BOOLEAN DEFAULT FALSE,
    sanctions_clear     BOOLEAN DEFAULT FALSE,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    version             INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_phone ON users(phone);
CREATE INDEX idx_users_kyc ON users(kyc_status);
CREATE INDEX idx_users_country ON users(residence_country);

-- ============================================================
-- WALLETS (Multi-Currency, Multi-Chain)
-- ============================================================
CREATE TABLE wallets (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL REFERENCES users(id),

    currency_code       VARCHAR(10) NOT NULL,
    currency_type       VARCHAR(10) NOT NULL
                        CHECK (currency_type IN ('FIAT', 'CRYPTO')),
    chain               VARCHAR(20),
    wallet_address      VARCHAR(128),
    address_tag         VARCHAR(64),

    balance             BIGINT NOT NULL DEFAULT 0 CHECK (balance >= 0),
    pending_balance     BIGINT NOT NULL DEFAULT 0 CHECK (pending_balance >= 0),
    locked_balance      BIGINT NOT NULL DEFAULT 0 CHECK (locked_balance >= 0),
    currency_decimals   SMALLINT NOT NULL DEFAULT 2,

    daily_limit         BIGINT,
    daily_used          BIGINT NOT NULL DEFAULT 0,
    monthly_limit       BIGINT,
    monthly_used        BIGINT NOT NULL DEFAULT 0,

    is_primary          BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version             INTEGER NOT NULL DEFAULT 1,

    UNIQUE(user_id, currency_code, chain)
);

CREATE INDEX idx_wallets_user ON wallets(user_id);
CREATE INDEX idx_wallets_currency ON wallets(currency_code, chain);

-- ============================================================
-- TRANSACTIONS
-- ============================================================
CREATE TABLE transactions (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    reference_id            VARCHAR(64) UNIQUE NOT NULL,

    sender_id               UUID NOT NULL REFERENCES users(id),
    recipient_id            UUID REFERENCES users(id),
    sender_wallet_id        UUID NOT NULL REFERENCES wallets(id),
    recipient_wallet_id     UUID REFERENCES wallets(id),

    source_currency         VARCHAR(10) NOT NULL,
    destination_currency    VARCHAR(10) NOT NULL,
    source_amount           BIGINT NOT NULL,
    destination_amount      BIGINT,
    fx_rate                 NUMERIC(18, 8),
    fx_rate_locked_at       TIMESTAMPTZ,

    bridge_currency         VARCHAR(10),
    bridge_chain            VARCHAR(20),
    bridge_amount           BIGINT,
    on_chain_tx_hash        VARCHAR(128),
    block_number            BIGINT,
    block_confirmations     INTEGER DEFAULT 0,

    on_ramp_fee             BIGINT DEFAULT 0,
    off_ramp_fee            BIGINT DEFAULT 0,
    network_fee             BIGINT DEFAULT 0,
    platform_fee            BIGINT DEFAULT 0,
    total_fee               BIGINT GENERATED ALWAYS AS
                            (on_ramp_fee + off_ramp_fee + network_fee + platform_fee) STORED,

    status                  VARCHAR(30) NOT NULL DEFAULT 'INITIATED'
                            CHECK (status IN (
                                'INITIATED', 'KYC_VERIFIED', 'FIAT_RECEIVED',
                                'STABLECOIN_MINTED', 'ON_CHAIN_SENT', 'ON_CHAIN_CONFIRMED',
                                'FIAT_DISBURSED', 'COMPLETED',
                                'FAILED', 'REFUNDING', 'REFUNDED', 'REJECTED'
                            )),
    failure_reason          TEXT,

    travel_rule_id          VARCHAR(128),
    compliance_status       VARCHAR(20) DEFAULT 'PENDING'
                            CHECK (compliance_status IN (
                                'PENDING', 'APPROVED', 'FLAGGED', 'REJECTED'
                            )),
    risk_score              SMALLINT DEFAULT 0,

    initiated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at            TIMESTAMPTZ,
    expires_at              TIMESTAMPTZ,

    idempotency_key         VARCHAR(64) UNIQUE,
    metadata                JSONB DEFAULT '{}',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version                 INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX idx_tx_sender ON transactions(sender_id);
CREATE INDEX idx_tx_recipient ON transactions(recipient_id);
CREATE INDEX idx_tx_status ON transactions(status);
CREATE INDEX idx_tx_reference ON transactions(reference_id);
CREATE INDEX idx_tx_created ON transactions(created_at);
CREATE INDEX idx_tx_chain ON transactions(bridge_chain, on_chain_tx_hash);

-- ============================================================
-- LEDGER ENTRIES (Double-Entry Bookkeeping)
-- ============================================================
CREATE TABLE ledger_entries (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transaction_id  UUID NOT NULL REFERENCES transactions(id),
    wallet_id       UUID NOT NULL REFERENCES wallets(id),

    entry_type      VARCHAR(10) NOT NULL
                    CHECK (entry_type IN ('DEBIT', 'CREDIT')),
    amount          BIGINT NOT NULL CHECK (amount > 0),
    currency_code   VARCHAR(10) NOT NULL,

    balance_before  BIGINT NOT NULL,
    balance_after   BIGINT NOT NULL,

    description     VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ledger_tx ON ledger_entries(transaction_id);
CREATE INDEX idx_ledger_wallet ON ledger_entries(wallet_id);

-- ============================================================
-- CORRIDORS (Admin Configuration)
-- ============================================================
CREATE TABLE corridors (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_country          CHAR(2) NOT NULL,
    destination_country     CHAR(2) NOT NULL,
    source_currency         VARCHAR(10) NOT NULL,
    destination_currency    VARCHAR(10) NOT NULL,
    preferred_chain         VARCHAR(20) NOT NULL DEFAULT 'polygon',
    preferred_stablecoin    VARCHAR(10) NOT NULL DEFAULT 'USDC',
    on_ramp_provider        VARCHAR(50) NOT NULL,
    off_ramp_provider       VARCHAR(50) NOT NULL,
    min_amount              BIGINT NOT NULL,
    max_amount              BIGINT NOT NULL,
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(source_country, destination_country)
);
