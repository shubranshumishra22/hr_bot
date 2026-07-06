"""Builds a local Chroma vector store from the markdown files in policies/.

Uses a local sentence-transformers embedding model, so this step needs
internet access ONCE (to download the model weights) but makes zero
paid/rate-limited API calls afterwards - embeddings run entirely on your
machine, free forever.

Run this whenever you add or edit a policy document:
    python -m rag.build_index
"""
import os
import sys
import glob

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CHROMA_DIR

from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import MarkdownTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_chroma import Chroma

POLICIES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "policies")


def load_policy_documents():
    docs = []
    for path in glob.glob(os.path.join(POLICIES_DIR, "*.md")):
        loader = TextLoader(path, encoding="utf-8")
        loaded = loader.load()
        for d in loaded:
            d.metadata["source"] = os.path.basename(path)
        docs.extend(loaded)
    return docs


def build_index():
    docs = load_policy_documents()
    print(f"Loaded {len(docs)} policy document(s) from {POLICIES_DIR}")

    splitter = MarkdownTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_documents(docs)
    print(f"Split into {len(chunks)} chunks")

    # Fully local, free embedding model - no API key, no rate limit.
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=CHROMA_DIR,
        collection_name="hr_policies",
    )
    print(f"Chroma index built and persisted at {CHROMA_DIR}")
    return vectorstore


if __name__ == "__main__":
    build_index()
