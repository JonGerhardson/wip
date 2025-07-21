# Personal Knowledge Base & RAG Engine

## Project Goals

This project aims to create a powerful, local-first document management system inspired by applications like `paperless-ngx`, but with a core focus on modern AI capabilities. The primary goal is to transform a directory of unorganized, mixed-media files into a fully searchable, intelligent knowledge base that you can "talk to."

The core workflow is designed to be simple yet powerful:

1.  **Ingest Documents:** Point the application at a directory of your files (`.pdf`, `.txt`, `.docx`, etc.). The system recursively scans the directory and processes each new file it finds.
2.  **AI-Powered Metadata Extraction:** For each document, the system uses a local Large Language Model (LLM) to perform deep analysis and extract key, structured metadata, including:
    * A concise **document title**.
    * The **document set** it belongs to (e.g., "Exhibit A," "Meeting Minutes").
    * The primary **document date**.
    * Standardized tags for **named individuals** and other important **named entities**.
    * A list of high-level **categories**.
    * A two-sentence **summary** of the document's content.
3.  **Dual-Database Architecture:** The extracted information is stored in two complementary databases to enable powerful hybrid search:
    * **SQLite Database:** All the structured metadata (title, date, entities, categories, etc.) is stored here. This allows for fast, precise, traditional keyword searches and filtering.
    * **ChromaDB (Vector Database):** The full text of each document is intelligently chunked. Each chunk is stored as a vector embedding, with the document's metadata appended. This enables powerful semantic search and forms the backbone of the RAG system.
4.  **Hybrid Search & RAG:** Through a simple web UI, users can interact with their knowledge base in two ways:
    * **Lexical Search:** A traditional keyword search that queries the SQLite database for fast, exact matches on titles, entities, or categories.
    * **RAG (Retrieval-Augmented Generation):** Ask complex, natural-language questions. The system finds the most relevant chunks of information from the vector database and uses an LLM to synthesize a direct, accurate answer with citations to the source documents.

---

## Current Limitations

This is a powerful proof-of-concept and a functional tool, but it currently has several limitations:

* **Local-First Only:** The entire application (backend, databases, document store) runs on your local machine. There is no cloud connectivity.
* **Requires Local LLM:** The system is designed to connect to a local LLM (like Ollama, LM Studio, etc.) running on `http://localhost:1234`. It does not currently support cloud-based LLM APIs.
* **Requires ExifTool:** For rich metadata extraction from non-text files (images, audio), the system relies on the command-line tool `ExifTool`. It will function without it, but metadata will be limited.
* **Simple UI:** The current user interface is functional for ingestion and search but lacks advanced features like a dedicated document viewer, metadata editing post-ingestion, or complex filtering options.
* **Basic Ingestion Workflow:** The system ingests all supported files from a directory. There is no functionality to ignore specific subfolders or file types via the UI.
* **No User Management:** The application is single-user and has no concept of accounts or permissions.

---

## Future Plans

The goal is to evolve this project into a fully-featured, robust alternative to existing document management systems. The roadmap includes:

* **Full RAG Query Interface:** Enhance the UI to better display RAG answers, allowing users to easily view source chunks and explore related documents.
* **Advanced Filtering:** Build UI components that allow users to combine lexical and semantic searches. For example: "Find documents *categorized as 'Financial'* that discuss *'Q3 budget projections'*."
* **In-App Document Viewer:** Integrate a document viewer (like PDF.js) so users can view their documents directly in the browser without needing to open them locally.
* **Post-Ingestion Editing:** Allow users to edit titles, summaries, tags, and other metadata directly from the web interface after a document has been ingested.
* **Support for Cloud LLM APIs:** Add optional support for services like OpenAI, Anthropic, or Google Gemini for users who prefer cloud-based models.
* **Dockerization:** Package the entire application (backend, dependencies, and even the vector DB) into a Docker container for easy, one-command deployment on any system.
* **Improved Error Handling & Resilience:** Make the ingestion process more robust, with better logging and the ability to retry failed documents.
* **Automated Tagging Rules:** Allow users to create rules to automatically tag documents based on filename, content, or source folder (e.g., "any file from `/invoices` gets the 'Financial' tag").
