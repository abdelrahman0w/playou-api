import httpx

from src.exceptions import EmailUnavailableError
from src.settings import settings
from src.utils import Singleton


class ResendService:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        sender: str,
    ) -> None:
        self._client = client
        self._sender = sender

    async def send(
        self,
        to: str,
        *,
        subject: str,
        html: str,
        text: str,
    ) -> None:
        try:
            response = await self._client.post(
                "/emails",
                json={
                    "from": self._sender,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                    "text": text,
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code

            raise EmailUnavailableError(
                f"The email could not be sent, resend answered {status}",
            ) from exc
        except httpx.HTTPError as exc:
            raise EmailUnavailableError("The email could not be sent") from exc

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
