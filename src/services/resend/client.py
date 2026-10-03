import httpx

from src.exceptions import EmailUnavailableError
from src.settings import settings
from src.structs.models import OutgoingEmail
from src.utils import Singleton


BATCH_SIZE = 100


class ResendService:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        sender: str,
    ) -> None:
        self._client = client
        self._sender = sender

    def _body(self, email: OutgoingEmail) -> dict[str, object]:
        return {
            "from": self._sender,
            "to": [email.to],
            "subject": email.subject,
            "html": email.html,
            "text": email.text,
        }

    async def _post(
        self,
        path: str,
        body: object,
        headers: dict[str, str] | None = None,
    ) -> None:
        try:
            response = await self._client.post(path, json=body, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code

            raise EmailUnavailableError(
                f"The email could not be sent, resend answered {status}",
            ) from exc
        except httpx.HTTPError as exc:
            raise EmailUnavailableError("The email could not be sent") from exc

    async def send(
        self,
        to: str,
        *,
        subject: str,
        html: str,
        text: str,
    ) -> None:
        await self._post(
            "/emails",
            self._body(OutgoingEmail(to=to, subject=subject, html=html, text=text)),
        )

    async def send_batch(
        self,
        emails: list[OutgoingEmail],
        *,
        idempotency_key: str | None = None,
    ) -> None:
        if len(emails) > BATCH_SIZE:
            raise ValueError(f"A batch takes {BATCH_SIZE} emails at most")

        await self._post(
            "/emails/batch",
            [self._body(email) for email in emails],
            {"Idempotency-Key": idempotency_key} if idempotency_key else None,
        )

    async def close(self) -> None:
        await self._client.aclose()


class ResendConnection(Singleton[ResendService | None]):
    @classmethod
    def create(cls) -> ResendService | None:
        resend = settings.resend
        if resend.api_key is None or not resend.api_key.get_secret_value():
            return None

        return ResendService(
            httpx.AsyncClient(
                base_url=resend.base_url,
                headers={
                    "Authorization": f"Bearer {resend.api_key.get_secret_value()}"
                },
                timeout=resend.timeout_seconds,
            ),
            sender=resend.sender,
        )

    @classmethod
    async def dispose(cls, instance: ResendService | None) -> None:
        if instance is not None:
            await instance.close()
