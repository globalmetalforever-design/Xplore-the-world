import os
import re
from urllib.parse import urlparse, parse_qs

import streamlit as st
from youtube_transcript_api import YouTubeTranscriptApi
from google import genai

st.set_page_config(page_title="YouTube Quick Summary", page_icon="▶️", layout="centered")

MODEL_NAME = "gemini-3.8-flash"
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
    text_parts = [snippet.text for snippet in fetched if snippet.text.strip()]
    transcript_text = " ".join(text_parts).strip()

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
    response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
    summary = (response.text or "").strip()
    if not summary:
        raise RuntimeError("Gemini returned an empty summary.")
    return summary


st.title("▶️ YouTube Quick Summary")
st.caption("Paste a YouTube link to get a short English summary.")

api_key = get_api_key()
if not api_key:
    st.error(
        "The Gemini API key has not been configured. "
        "The app administrator must add GEMINI_API_KEY in Streamlit Secrets."
    )
    st.stop()

video_url = st.text_input(
    "YouTube video link",
    placeholder="https://www.youtube.com/watch?v=...",
)
generate = st.button("Generate short summary", type="primary", use_container_width=True)

if generate:
    for key in ("summary_result", "summary_video_id", "summary_language"):
        st.session_state.pop(key, None)

    video_id = extract_video_id(video_url)
    if not video_id:
        st.error("Please enter a valid YouTube video link.")
    else:
        try:
            with st.spinner("Getting video captions..."):
                transcript_text, transcript_language = fetch_transcript(video_id)
            with st.spinner("Preparing your short summary..."):
                summary = make_short_summary(transcript_text, api_key)

            st.session_state["summary_result"] = summary
            st.session_state["summary_video_id"] = video_id
            st.session_state["summary_language"] = transcript_language
        except Exception as exc:
            st.error(
                "I couldn't summarise this video. It may not have accessible captions, "
                "or YouTube may have temporarily blocked transcript access."
            )
            with st.expander("Technical detail"):
                st.code(str(exc))

if st.session_state.get("summary_result"):
    video_id = st.session_state["summary_video_id"]
    st.divider()
    st.subheader("Summary")
    st.markdown(st.session_state["summary_result"])
    st.caption("Caption language: " + str(st.session_state.get("summary_language", "Unknown")))
    st.markdown(f"[Watch this video on YouTube](https://www.youtube.com/watch?v={video_id})")

    if st.button("Clear summary", use_container_width=True):
        for key in ("summary_result", "summary_video_id", "summary_language"):
            st.session_state.pop(key, None)
        st.rerun()

st.divider()
st.caption(
    "Summaries are not saved to a database or file. "
    "They remain temporarily in the active app session."
)
