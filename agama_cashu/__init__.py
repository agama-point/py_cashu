"""Small library modules behind the Agama Cashu Qt app."""

__all__ = ["CashuWorker", "CashuWrapper"]


def __getattr__(name: str):
    if name == "CashuWrapper":
        from .cashu_wrapper import CashuWrapper

        return CashuWrapper
    if name == "CashuWorker":
        from .cashuworker import CashuWorker

        return CashuWorker
    raise AttributeError(f"module 'agama_cashu' has no attribute {name!r}")
