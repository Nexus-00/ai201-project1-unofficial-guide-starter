"""
app.py — Gradio web interface for the Seattle RAG pipeline.

A thin front end over prompt_me.ask(): type a question, get the model's answer
(grounded only in retrieved chunks), the sources it drew from, and its thinking.

    python app.py

Requires the ChromaDB index (run embed_data.py first) and GROQ_API_KEY in .env.
"""

import gradio as gr

from prompt_me import ask


def handle_query(question: str):
    """Run one RAG query; return (answer, sources, thinking) for the UI."""
    if not question or not question.strip():
        return "Please enter a question.", "", ""
    try:
        result = ask(question)
    except RuntimeError as e:
        return f"Error: {e}", "", ""
    except Exception as e:  # network/API failures (e.g. Groq edge 403)
        return f"Request failed: {type(e).__name__}: {e}", "", ""

    sources = "\n".join(f"• {s}" for s in result["sources"])
    return result["answer"], sources, result["reasoning"]


with gr.Blocks(title="The Unofficial Guide to Seattle") as demo:
    gr.Markdown(
        "# The Unofficial Guide to Seattle\n"
        "Ask about apartments, rent, neighborhoods, and living in Seattle. "
        "Answers come only from the indexed sources."
    )
    inp = gr.Textbox(label="Your question", placeholder="e.g. What are rent prices in Seattle?")
    btn = gr.Button("Ask", variant="primary")
    answer = gr.Textbox(label="Answer", lines=8)
    sources = gr.Textbox(label="Retrieved from", lines=4)
    with gr.Accordion("Model thinking", open=False):
        thinking = gr.Textbox(label="Reasoning", lines=8)

    outputs = [answer, sources, thinking]
    btn.click(handle_query, inputs=inp, outputs=outputs)
    inp.submit(handle_query, inputs=inp, outputs=outputs)


if __name__ == "__main__":
    demo.launch()
