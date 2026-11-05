import os
import re
import time
from urllib.parse import urlparse, parse_qs

import streamlit as st
from youtube_transcript_api import YouTubeTranscriptApi
from google import genai

st.set_page_config(page_title="YouTube Quick Summary", page_icon="▶️", layout="centered")

# Current Gemini API model names. Models are tried in this order.
MODEL_NAMES = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
]
PREFERRED_LANGUAGES = ["kn", "ta", "hi", "en", "en-US"]


def get_api_key():
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
        if key:
            return str(key).strip()
    except Exception:
        pass
    return os.getenv("GEMINI_API_KEY", "").strip()


def extract_video_id(url):
    if not url:
        return None
    try:
        parsed = urlparse(url.strip())
        host = (parsed.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if host in ("youtube.com", "m.youtube.com", "music.youtube.com"):
            if parsed.path == "/watch":
                video_id = parse_qs(parsed.query).get("v", [None])[0]
            elif parsed.path.startswith(("/shorts/", "/embed/")):
                parts = parsed.path.strip("/").split("/")
                video_id = parts[1] if len(parts) > 1 else None
            else:
                video_id = None
        elif host == "youtu.be":
            video_id = parsed.path.strip("/").split("/")[0]
        else:
            video_id = None
        return video_id if video_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) else None
    except Exception:
        return None


def fetch_transcript(video_id):
    api = YouTubeTranscriptApi()
    transcript_list = api.list(video_id)
    try:
        transcript = transcript_list.find_transcript(PREFERRED_LANGUAGES)
    except Exception:
        try:
            transcript = transcript_list.find_generated_transcript(PREFERRED_LANGUAGES)
        except Exception:
            try:
                transcript = next(iter(transcript_list))
            except StopIteration:
                raise ValueError("This video does not appear to have captions or a transcript.")
    fetched = transcript.fetch()
    transcript_text = " ".join(
        snippet.text for snippet in fetched if snippet.text.strip()
    ).strip()
    if not transcript_text:
        raise ValueError("The available transcript is empty.")
    return transcript_text, getattr(transcript, "language", "Unknown")


def make_short_summary(transcript_text, api_key):
    client = genai.Client(api_key=api_key)
    prompt = f"""
Summarise this YouTube video transcript in clear, natural English.

Requirements:
- Keep the entire summary approximately 80–130 words.
- Start with the central message of the video.
- Then provide 3–5 short bullet points with only the most important information.
- Do not add chapter breakdowns, lengthy explanations, outside research, or opinions.
- Do not invent facts that are absent from the transcript.
- The transcript may be in Kannada, Tamil, Hindi, or English. Understand it and write in English.
- If the transcript is incomplete or unclear, say so briefly rather than guessing.

TRANSCRIPT:
{transcript_text[:50000]}
"""
    transient_markers = (
        "503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED",
        "high demand", "overloaded", "temporarily unavailable",
    )
    errors = []
    for model_name in MODEL_NAMES:
        for attempt, delay in enumerate((0, 3, 8), start=1):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                result = (response.text or "").strip()
                if not result:
                    raise RuntimeError("Gemini returned an empty summary.")
                return result, model_name
            except Exception as exc:
                message = str(exc)
                errors.append(f"{model_name}: {message}")
                temporary = any(x.lower() in message.lower() for x in transient_markers)
                if temporary and attempt < 3:
                    time.sleep(delay)
                    continue
                if temporary:
                    break
                raise
    raise RuntimeError(
        "Gemini could not process the request after automatic retries and model fallback. "
        "Please try again later.\n\n" + "\n".join(errors[-4:])
    )


st.title("▶️ YouTube Quick Summary")
st.caption("Paste a YouTube link to get one short English summary.")

api_key = get_api_key()
if not api_key:
    st.error(
        "The Gemini API key has not been configured. "
        "Add GEMINI_API_KEY in this app's Streamlit Secrets."
    )
    st.stop()

video_url = st.text_input(
    "YouTube video link",
    placeholder="https://www.youtube.com/watch?v=...",
)
generate = st.button("Generate short summary", type="primary", use_container_width=True)

if generate:
    for item in ("summary_result", "summary_video_id", "summary_language", "summary_model"):
        st.session_state.pop(item, None)
    video_id = extract_video_id(video_url)
    if not video_id:
        st.error("Please enter a valid YouTube video link.")
    else:
        try:
            with st.spinner("Getting video captions..."):
                transcript_text, language = fetch_transcript(video_id)
            with st.spinner("Preparing your short summary..."):
                summary, model_used = make_short_summary(transcript_text, api_key)
            st.session_state["summary_result"] = summary
            st.session_state["summary_video_id"] = video_id
            st.session_state["summary_language"] = language
            st.session_state["summary_model"] = model_used
        except Exception as exc:
            detail = str(exc)
            st.error("I couldn't summarise this video.")
            if any(x in detail.lower() for x in (
                "503", "unavailable", "429", "resource_exhausted", "high demand"
            )):
                st.caption(
                    "Gemini is temporarily overloaded or unavailable. "
                    "Automatic retries and fallback models have already been attempted."
                )
            elif "transcript" in detail.lower() or "caption" in detail.lower():
                st.caption(
                    "YouTube did not provide accessible captions for this video. "
                    "Only videos with accessible captions can be summarised."
                )
            with st.expander("Technical detail"):
                st.code(detail)

if st.session_state.get("summary_result"):
    video_id = st.session_state["summary_video_id"]
    st.divider()
    st.subheader("Summary")
    st.markdown(st.session_state["summary_result"])
    st.caption(
        f"Caption language: {st.session_state.get('summary_language', 'Unknown')} "
        f"· Model: {st.session_state.get('summary_model', 'Unknown')}"
    )
    st.markdown(f"[Watch this video on YouTube](https://www.youtube.com/watch?v={video_id})")
    if st.button("Clear summary", use_container_width=True):
        for item in ("summary_result", "summary_video_id", "summary_language", "summary_model"):
            st.session_state.pop(item, None)
        st.rerun()

st.divider()
st.caption("Summaries are not saved to a database or file.")
