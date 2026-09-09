from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document

_LOADERS = {".pdf": PyPDFLoader, ".txt": TextLoader, ".md": TextLoader}


def load_documents(data_dir: str) -> list[Document]:
    path = Path(data_dir)
    files = (
        [f for f in path.iterdir() if f.suffix.lower() in _LOADERS]
        if path.is_dir()
        else []
    )

    if not files:
        raise FileNotFoundError(
            f"No documents found in {data_dir}. Add .txt, .md, or .pdf files to ingest."
        )

    documents = []
    for file in sorted(files):
        documents.extend(_LOADERS[file.suffix.lower()](str(file)).load())
    return documents
