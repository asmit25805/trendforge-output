from __future__ import annotations

import json
import re
from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, validator

# Regular expression for a simple Ethereum address validation (checks 0x prefix and length)
_ETH_ADDRESS_REGEX = re.compile(r"^0x[a-fA-F0-9]{40}$")


def _validate_eth_address(value: str) -> str:
    """Validate that a string looks like an Ethereum address."""
    if not _ETH_ADDRESS_REGEX.fullmatch(value):
        raise ValueError(f"Invalid Ethereum address: {value}")
    return value.lower()


class RouterStep(BaseModel):
    """
    Represents a single router call inside an arbitrage path.
    """

    router_address: str = Field(..., description="Whitelist‑checked router contract address")
    fee_tier: int = Field(..., ge=0, description="Uniswap V3 fee tier (e.g., 500, 3000)")
    swap_data: bytes = Field(..., description="Encoded calldata for the router")

    @validator("router_address")
    def check_router_address(cls, v: str) -> str:
        return _validate_eth_address(v)

    def to_dict(self) -> dict:
        """Return a JSON‑serialisable representation."""
        return {
            "router_address": self.router_address,
            "fee_tier": self.fee_tier,
            "swap_data": self.swap_data.hex(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> RouterStep:
        """Create a RouterStep from a dictionary."""
        return cls(
            router_address=data["router_address"],
            fee_tier=data["fee_tier"],
            swap_data=bytes.fromhex(data["swap_data"]),
        )


class ArbOpportunity(BaseModel):
    """
    Candidate arbitrage trade built from on‑chain data.
    """

    source_chain: int = Field(..., ge=1, description="EVM chain ID where the trade starts")
    target_chain: int = Field(..., ge=1, description="Destination chain (same as source for intra‑chain arb)")
    router_path: List[RouterStep] = Field(..., description="Ordered list of router contracts to call")
    input_token: str = Field(..., description="Address of the token to spend")
    output_token: str = Field(..., description="Address of the token to receive")
    input_amount: int = Field(..., ge=0, description="Raw amount in wei")
    estimated_profit: int = Field(..., ge=0, description="Profit in wei after fees")

    @validator("input_token", "output_token")
    def check_token_address(cls, v: str) -> str:
        return _validate_eth_address(v)

    @validator("router_path")
    def non_empty_path(cls, v: List[RouterStep]) -> List[RouterStep]:
        if not v:
            raise ValueError("router_path must contain at least one RouterStep")
        return v

    def total_fee_tier(self) -> int:
        """Sum of fee tiers across the router path."""
        return sum(step.fee_tier for step in self.router_path)

    def to_dict(self) -> dict:
        """Serialise the opportunity to a plain dict."""
        return {
            "source_chain": self.source_chain,
            "target_chain": self.target_chain,
            "router_path": [step.to_dict() for step in self.router_path],
            "input_token": self.input_token,
            "output_token": self.output_token,
            "input_amount": self.input_amount,
            "estimated_profit": self.estimated_profit,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ArbOpportunity:
        """Deserialize an opportunity from a dict."""
        router_path = [RouterStep.from_dict(step) for step in data["router_path"]]
        return cls(
            source_chain=data["source_chain"],
            target_chain=data["target_chain"],
            router_path=router_path,
            input_token=data["input_token"],
            output_token=data["output_token"],
            input_amount=data["input_amount"],
            estimated_profit=data["estimated_profit"],
        )


class ExecutionResult(BaseModel):
    """
    Result of a transaction that attempted to execute an arbitrage opportunity.
    """

    tx_hash: str = Field(..., description="Transaction hash of the executed bundle")
    success: bool = Field(..., description="True if the transaction did not revert")
    actual_profit: int = Field(..., ge=0, description="Realized profit in wei")
    gas_used: int = Field(..., ge=0, description="Gas consumed by the transaction")
    gas_price: int = Field(..., ge=0, description="Gas price (wei per gas) used for the transaction")

    @validator("tx_hash")
    def check_tx_hash(cls, v: str) -> str:
        return _validate_eth_address(v)

    def net_profit(self) -> int:
        """Profit after deducting gas cost."""
        return self.actual_profit - self.gas_used * self.gas_price

    def to_json(self) -> str:
        """Encode the result as a JSON string."""
        return json.dumps(
            {
                "tx_hash": self.tx_hash,
                "success": self.success,
                "actual_profit": self.actual_profit,
                "gas_used": self.gas_used,
                "gas_price": self.gas_price,
                "net_profit": self.net_profit(),
            }
        )


class ProfitReport(BaseModel):
    """
    Daily aggregated profit statistics.
    """

    date: date = Field(..., description="Day of the report")
    total_profit: int = Field(..., ge=0, description="Sum of actual_profit for the day")
    total_gas_cost: int = Field(..., ge=0, description="Sum of gas_used * gas_price")
    total_deposited: int = Field(..., ge=0, description="Total capital deposited on that day")
    roi: float = Field(..., description="(total_profit - total_gas_cost) / total_deposited")

    @validator("roi", always=True)
    def compute_roi(cls, v: Optional[float], values: dict) -> float:
        profit = values.get("total_profit", 0)
        gas = values.get("total_gas_cost", 0)
        deposited = values.get("total_deposited", 0)
        if deposited == 0:
            return 0.0
        return (profit - gas) / deposited

    def to_csv_row(self) -> str:
        """Return a CSV row representing the report."""
        return f"{self.date.isoformat()},{self.total_profit},{self.total_gas_cost},{self.total_deposited},{self.roi:.6f}"

    @classmethod
    def from_csv_row(cls, row: str) -> ProfitReport:
        """Parse a CSV row into a ProfitReport."""
        parts = row.strip().split(",")
        if len(parts) != 5:
            raise ValueError("CSV row must have exactly 5 fields")
        report_date = date.fromisoformat(parts[0])
        total_profit = int(parts[1])
        total_gas_cost = int(parts[2])
        total_deposited = int(parts[3])
        roi = float(parts[4])
        return cls(
            date=report_date,
            total_profit=total_profit,
            total_gas_cost=total_gas_cost,
            total_deposited=total_deposited,
            roi=roi,
        )


class InvalidOpportunity(Exception):
    """
    Raised when an ArbOpportunity fails whitelist validation.
    The engine catches this exception and discards the candidate.
    """

    def __init__(self, opportunity: ArbOpportunity, reason: str) -> None:
        self.opportunity = opportunity
        self.reason = reason
        super().__init__(f"Invalid opportunity: {reason}")


__all__ = [
    "RouterStep",
    "ArbOpportunity",
    "ExecutionResult",
    "ProfitReport",
    "InvalidOpportunity",
]