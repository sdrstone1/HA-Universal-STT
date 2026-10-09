# Release notes

## 0.3.0

HA Universal Voice provides STT, TTS, or both through OpenAI, Google Gemini,
xAI, OpenRouter, and OpenAI-compatible audio APIs. Existing `universal_stt`
installations and entity IDs are preserved.

- Separates configuration, credentials, provider clients, HTTP transport, and
  entry-owned request/stream cleanup.
- Uses provider-specific setup forms and separate STT/TTS model selection.
- Supports optional TTS output streaming after collecting the full input text.
- Handles OpenRouter MP3, WAV, and PCM responses using their actual format.
  Request formats are configurable in `model_audio_formats.json`: PCM by
  default, with an MP3 exception for MiniMax Speech 2.8 HD.
- Includes English/Korean setup screens and installation documentation.

Requires Home Assistant 2026.3.0 or newer. The existing product verification
covered 176 unit tests and 88 HA integration tests on each of HA 2026.3.0 and
2026.10.0. Real OpenRouter playback was confirmed for Gemini, Mistral, and
MiniMax Speech 2.8 HD. OpenAI/xAI live playback was not tested because keys
were unavailable; automated provider-response tests are not live playback.

Install through the HACS custom repository or copy
`custom_components/universal_stt/` into `/config/custom_components/`, then
restart Home Assistant. Existing STT entries remain STT-only until TTS is
enabled in their options. A ZIP asset is for manual extraction; it does not
add a ZIP-upload installer to the Home Assistant web interface.

### 한국어

설정·인증·공급자·통신·요청 수명을 분리한 STT/TTS 재설계 버전입니다.
기존 설치 폴더와 엔티티 ID를 유지하며, 공급자별 설정 화면과 선택형 출력
스트리밍을 제공합니다. OpenRouter는 실제 응답 형식으로 재생하고, 별도
JSON에서 기본 PCM과 MiniMax Speech 2.8 HD의 MP3 예외를 관리합니다.

Home Assistant 2026.3.0 이상이 필요합니다. OpenRouter 세 모델의 실제 재생을
확인했으며 OpenAI·xAI 실계정 재생은 미확인입니다. 기존 STT 설정은 옵션에서
TTS를 활성화한 뒤 사용할 수 있습니다. 설치·업데이트 후 HA를 재시작하세요.
