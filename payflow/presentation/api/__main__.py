import uvicorn

from payflow.infra.config import ServiceConfig


def main() -> None:
    ServiceConfig()
    uvicorn.run(
        "payflow.presentation.api.application:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
