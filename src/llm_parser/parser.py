import json
import os
from datetime import datetime, timezone
from typing import Optional
import anthropic
from pydantic import ValidationError

from ..models import Event
from .prompts import SYSTEM_PROMPT, build_user_prompt


class ParsingError(Exception):
    """Raised when LLM parsing fails or produces invalid output."""

    pass


class LLMParser:
    """
    Parses unstructured Discord messages into structured Event objects.

    Uses Claude with temperature=0 for deterministic parsing.
    Strict schema validation via Pydantic.
    Fail-safe: any ambiguity or validation error => NO TRADE.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-opus-4-5-20251101",
        temperature: float = 0.0,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY must be set")

        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = model
        self.temperature = temperature

    def parse_message(
        self,
        message: str,
        author: str,
        message_id: str,
        timestamp: Optional[datetime] = None,
    ) -> Event:
        """
        Parse a Discord message into a structured Event.

        Args:
            message: Raw Discord message text
            author: Discord username
            message_id: Discord message ID (for idempotency)
            timestamp: Message timestamp (defaults to now)

        Returns:
            Event object

        Raises:
            ParsingError: If parsing fails, LLM returns invalid JSON,
                         or validation fails
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        # Build prompt
        user_prompt = build_user_prompt(
            message=message,
            author=author,
            timestamp=timestamp.isoformat(),
        )

        try:
            # Call LLM
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                temperature=self.temperature,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )

            # Extract response
            raw_response = response.content[0].text.strip()

            # Debug: print what LLM returned
            print(f"  LLM full response:\n{raw_response}\n")

            # Try to extract JSON from markdown code blocks if present
            if raw_response.startswith("```"):
                # Remove markdown code blocks
                lines = raw_response.split('\n')
                json_lines = []
                in_code_block = False
                for line in lines:
                    if line.startswith("```"):
                        in_code_block = not in_code_block
                        continue
                    if in_code_block or not line.startswith("```"):
                        json_lines.append(line)
                raw_response = '\n'.join(json_lines).strip()

            # Parse JSON
            try:
                event_dict = json.loads(raw_response)
            except json.JSONDecodeError as e:
                print(f"  Raw LLM response:\n{raw_response}")
                raise ParsingError(f"LLM returned invalid JSON: {e}") from e

            # Add metadata not provided by LLM
            event_dict["timestamp"] = timestamp.isoformat()
            event_dict["author"] = author
            event_dict["message_id"] = message_id
            event_dict["raw_message"] = message

            # Validate with Pydantic
            try:
                event = Event(**event_dict)
            except ValidationError as e:
                raise ParsingError(f"Event validation failed: {e}") from e

            # Final fail-safe: low confidence => fail
            if event.parsing_confidence and event.parsing_confidence < 0.7:
                raise ParsingError(
                    f"Low parsing confidence: {event.parsing_confidence:.2f}"
                )

            return event

        except anthropic.APIError as e:
            raise ParsingError(f"Anthropic API error: {e}") from e

    def parse_batch(
        self,
        messages: list[dict],
    ) -> list[Event]:
        """
        Parse multiple messages in sequence.

        Args:
            messages: List of dicts with keys: message, author, message_id, timestamp

        Returns:
            List of successfully parsed Events (failures are skipped with logging)
        """
        events = []
        for msg in messages:
            try:
                event = self.parse_message(
                    message=msg["message"],
                    author=msg["author"],
                    message_id=msg["message_id"],
                    timestamp=msg.get("timestamp"),
                )
                events.append(event)
            except ParsingError as e:
                # Log but don't crash - fail-safe behavior
                print(f"Failed to parse message {msg['message_id']}: {e}")
                continue

        return events
