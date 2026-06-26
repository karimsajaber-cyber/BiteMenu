document.addEventListener("DOMContentLoaded", () => {
    const micBtn = document.getElementById("micBtn");
    const responseText = document.getElementById("responseText");
    const audioPlayer = document.getElementById("audioPlayer");
    const restaurantId = document.querySelector('meta[name="restaurant-id"]')?.content || "";
    const availableItemsCount = Number(
        document.querySelector('meta[name="available-items-count"]')?.content || "0"
    );
    const DEFAULT_MESSAGE = "ما فهمت عليك";
    const recognitionLangs = ["ar-PS", "ar", "ar-SA"];
    const MAX_RECORD_MS = 8000;
    const SILENCE_MS = 900;
    const MIN_AUDIO_BYTES = 1800;
    const SILENCE_THRESHOLD = 0.018;

    if (!micBtn || !responseText || !audioPlayer) return;

    let isListening = false;
    let isRecording = false;
    let recognition = null;
    let currentLangIndex = 0;
    let pendingRetry = false;
    let mediaRecorder = null;
    let mediaStream = null;
    let recordStopTimer = null;
    let audioChunks = [];
    let audioContext = null;
    let analyser = null;
    let analyserData = null;
    let audioMonitorFrame = null;
    let speechDetected = false;
    let lastSpeechAt = 0;

    function getCookie(name) {
        const cookies = document.cookie ? document.cookie.split(";") : [];

        for (const cookie of cookies) {
            const trimmed = cookie.trim();

            if (trimmed.startsWith(`${name}=`)) {
                return decodeURIComponent(trimmed.slice(name.length + 1));
            }
        }

        return "";
    }

    function csrfToken() {
        return (
            getCookie("csrftoken") ||
            document.querySelector("[name=csrfmiddlewaretoken]")?.value ||
            document.querySelector('meta[name="csrf-token"]')?.content ||
            ""
        );
    }

    function showMessage(message) {
        responseText.innerText = message || DEFAULT_MESSAGE;
    }

    function speakInBrowser(message) {
        if (!window.speechSynthesis || !message) return;

        window.speechSynthesis.cancel();

        const utterance = new SpeechSynthesisUtterance(message);
        utterance.lang = "ar";
        utterance.rate = 0.95;
        window.speechSynthesis.speak(utterance);
    }

    function stopAudioPlayback() {
        audioPlayer.pause();
        audioPlayer.currentTime = 0;
        audioPlayer.removeAttribute("src");
        audioPlayer.load();
        window.speechSynthesis?.cancel();
    }

    async function fetchWithTimeout(url, options = {}, timeoutMs = 10000) {
        const controller = new AbortController();
        const timeout = window.setTimeout(() => controller.abort(), timeoutMs);

        try {
            return await fetch(url, {
                ...options,
                signal: controller.signal,
            });
        } finally {
            window.clearTimeout(timeout);
        }
    }

    async function speakMessage(message) {
        try {
            const audioRes = await fetchWithTimeout("/tts/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken(),
                },
                body: JSON.stringify({ text: message }),
            }, 10000);

            const contentType = audioRes.headers.get("content-type") || "";

            if (!audioRes.ok || !contentType.includes("audio/")) {
                speakInBrowser(message);
                return;
            }

            const audioBlob = await audioRes.blob();
            const audioUrl = URL.createObjectURL(audioBlob);

            audioPlayer.src = audioUrl;
            audioPlayer.onended = () => URL.revokeObjectURL(audioUrl);
            await audioPlayer.play();
        } catch (error) {
            console.error("Voice playback failed:", error);
            speakInBrowser(message);
        }
    }

    function isSecureVoiceContext() {
        const hostname = window.location.hostname;

        if (window.isSecureContext) {
            return true;
        }

        return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
    }

    function stopAudioMonitor() {
        if (audioMonitorFrame) {
            window.cancelAnimationFrame(audioMonitorFrame);
            audioMonitorFrame = null;
        }

        if (audioContext) {
            audioContext.close().catch(() => { });
            audioContext = null;
        }

        analyser = null;
        analyserData = null;
        speechDetected = false;
        lastSpeechAt = 0;
    }

    function cleanupMediaStream() {
        if (recordStopTimer) {
            window.clearTimeout(recordStopTimer);
            recordStopTimer = null;
        }

        stopAudioMonitor();

        if (mediaStream) {
            mediaStream.getTracks().forEach((track) => track.stop());
            mediaStream = null;
        }

        mediaRecorder = null;
        audioChunks = [];
        isRecording = false;
    }

    async function sendRecognizedText(text) {
        try {
            const res = await fetchWithTimeout("/voice_order/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken(),
                },
                body: JSON.stringify({ text, restaurant_id: restaurantId }),
            }, 6000);

            const data = await res.json();
            const message = data.message || DEFAULT_MESSAGE;

            showMessage(message);
            await speakMessage(message);
        } catch (error) {
            console.error("Voice order failed:", error);
            const message = "صار خطأ بالصوت";
            showMessage(message);
            speakInBrowser(message);
        }
    }

    async function transcribeAudio(blob) {
        const formData = new FormData();
        formData.append("audio", blob, "voice.webm");

        const response = await fetchWithTimeout("/stt/", {
            method: "POST",
            headers: {
                "X-CSRFToken": csrfToken(),
            },
            body: formData,
        }, 30000);

        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(data.message || "stt failed");
        }

        return (data.text || "").trim();
    }

    function recorderMimeType() {
        const candidates = [
            "audio/webm;codecs=opus",
            "audio/webm",
            "audio/mp4",
        ];

        for (const candidate of candidates) {
            if (window.MediaRecorder?.isTypeSupported?.(candidate)) {
                return candidate;
            }
        }

        return "";
    }

    function stopRecorder() {
        if (mediaRecorder && mediaRecorder.state !== "inactive") {
            mediaRecorder.stop();
        }
    }

    function startAudioMonitor(stream) {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;

        if (!AudioContextClass) {
            return;
        }

        audioContext = new AudioContextClass();
        const source = audioContext.createMediaStreamSource(stream);
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 2048;
        analyserData = new Uint8Array(analyser.fftSize);
        source.connect(analyser);

        const tick = () => {
            if (!analyser || !analyserData || !isRecording) {
                return;
            }

            analyser.getByteTimeDomainData(analyserData);

            let sum = 0;
            for (const value of analyserData) {
                const normalized = (value - 128) / 128;
                sum += normalized * normalized;
            }

            const rms = Math.sqrt(sum / analyserData.length);
            const now = Date.now();

            if (rms >= SILENCE_THRESHOLD) {
                speechDetected = true;
                lastSpeechAt = now;
            }

            if (speechDetected && lastSpeechAt && now - lastSpeechAt >= SILENCE_MS) {
                stopRecorder();
                return;
            }

            audioMonitorFrame = window.requestAnimationFrame(tick);
        };

        audioMonitorFrame = window.requestAnimationFrame(tick);
    }

    async function startRecorderFlow() {
        if (isRecording) {
            stopRecorder();
            return;
        }

        if (availableItemsCount === 0) {
            const message = "حاليًا ما في أصناف متوفرة على المنيو";
            showMessage(message);
            await speakMessage(message);
            return;
        }

        if (!isSecureVoiceContext()) {
            const message = "شغّل الصفحة على localhost أو HTTPS عشان المايك يشتغل";
            showMessage(message);
            speakInBrowser(message);
            return;
        }

        if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
            startRecognitionFallback();
            return;
        }

        stopAudioPlayback();

        try {
            mediaStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                },
            });

            const mimeType = recorderMimeType();
            mediaRecorder = mimeType
                ? new MediaRecorder(mediaStream, { mimeType })
                : new MediaRecorder(mediaStream);

            audioChunks = [];
            isRecording = true;
            speechDetected = false;
            lastSpeechAt = 0;
            showMessage("احكي هسّه");

            mediaRecorder.ondataavailable = (event) => {
                if (event.data && event.data.size > 0) {
                    audioChunks.push(event.data);
                }
            };

            mediaRecorder.onerror = async () => {
                cleanupMediaStream();
                const message = "صار خطأ بالسماع";
                showMessage(message);
                await speakMessage(message);
            };

            mediaRecorder.onstop = async () => {
                const mime = mediaRecorder?.mimeType || "audio/webm";
                const audioBlob = new Blob(audioChunks, { type: mime });

                cleanupMediaStream();

                if (audioBlob.size < MIN_AUDIO_BYTES) {
                    const message = "احكي أوضح وقرب من المايك";
                    showMessage(message);
                    await speakMessage(message);
                    return;
                }

                try {
                    const text = await transcribeAudio(audioBlob);

                    if (!text) {
                        const message = DEFAULT_MESSAGE;
                        showMessage(message);
                        await speakMessage(message);
                        return;
                    }

                    await sendRecognizedText(text);
                } catch (error) {
                    console.error("STT failed:", error);
                    const message = "صار خطأ بالسماع";
                    showMessage(message);
                    await speakMessage(message);
                }
            };

            mediaRecorder.start(250);
            startAudioMonitor(mediaStream);
            recordStopTimer = window.setTimeout(stopRecorder, MAX_RECORD_MS);
        } catch (error) {
            console.error("Recorder start failed:", error);
            cleanupMediaStream();
            startRecognitionFallback();
        }
    }

    function recognitionErrorMessage(error) {
        switch (error) {
            case "not-allowed":
            case "service-not-allowed":
                return "فعّل إذن المايك";
            case "audio-capture":
                return "تأكد المايك شغال";
            case "network":
                return "صار خطأ بالسماع";
            case "language-not-supported":
                return "لغة السماع مش مدعومة بهالمتصفح";
            case "aborted":
            case "no-speech":
            default:
                return "ما سمعتك منيح";
        }
    }

    function startRecognitionFallback() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

        if (availableItemsCount === 0) {
            const message = "حاليًا ما في أصناف متوفرة على المنيو";
            showMessage(message);
            speakInBrowser(message);
            return;
        }

        if (!SpeechRecognition) {
            const message = "المتصفح ما بدعم المايك";
            showMessage(message);
            speakInBrowser(message);
            return;
        }

        if (isListening) return;

        if (!isSecureVoiceContext()) {
            const message = "شغّل الصفحة على localhost أو HTTPS عشان المايك يشتغل";
            showMessage(message);
            speakInBrowser(message);
            return;
        }

        stopAudioPlayback();
        recognition = new SpeechRecognition();
        recognition.lang = recognitionLangs[currentLangIndex];
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.maxAlternatives = 1;

        recognition.onstart = () => {
            isListening = true;
            showMessage("احكي هسّه");
        };

        recognition.onend = () => {
            isListening = false;

            if (!pendingRetry) {
                return;
            }

            pendingRetry = false;
            window.setTimeout(startRecognitionFallback, 150);
        };

        recognition.onresult = async (event) => {
            const text = event.results?.[0]?.[0]?.transcript?.trim();

            if (!text) {
                showMessage(DEFAULT_MESSAGE);
                await speakMessage(DEFAULT_MESSAGE);
                return;
            }

            await sendRecognizedText(text);
        };

        recognition.onerror = async (event) => {
            isListening = false;
            console.error("Recognition error:", event.error, "lang:", recognition.lang);

            if (event.error === "network" && currentLangIndex < recognitionLangs.length - 1) {
                currentLangIndex += 1;
                pendingRetry = true;
                showMessage("في مشكلة بالسماع، بجرب مرة ثانية");
                return;
            }

            const message = recognitionErrorMessage(event.error);
            showMessage(message);
            await speakMessage(message);
        };

        try {
            recognition.start();
        } catch (error) {
            console.error("Recognition start failed:", error);
            const message = "جرّب احكي مرة ثانية";
            showMessage(message);
            speakMessage(message);
        }
    }

    micBtn.onclick = () => {
        currentLangIndex = 0;
        pendingRetry = false;
        startRecorderFlow();
    };
});

(() => {
    const CTA_SELECTOR = ".cta-border";
    const STROKE_WIDTH = 2.5;
    const SPEED_PX_PER_SECOND = 84;
    const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const ctaStates = [];
    const ctaStateMap = new WeakMap();
    let rafId = 0;
    let activeCount = 0;
    let lastFrameTime = 0;

    function setWormVisible(state, visible) {
        if (state.worm) {
            state.worm.style.opacity = visible ? "1" : "0";
        }
    }

    function syncPaintServers(state, index) {
        if (
            !state.gradient ||
            !state.softBlur ||
            !state.coreBlur ||
            !state.mask ||
            !state.worm ||
            !state.softGlow ||
            !state.coreGlow
        ) {
            return;
        }

        const prefix = `cta-border-${index + 1}`;
        const gradientId = `${prefix}-gradient`;
        const softBlurId = `${prefix}-soft-blur`;
        const coreBlurId = `${prefix}-core-blur`;
        const maskId = `${prefix}-mask`;

        state.gradient.id = gradientId;
        state.softBlur.id = softBlurId;
        state.coreBlur.id = coreBlurId;
        state.mask.id = maskId;

        state.softGlow.setAttribute("fill", `url(#${gradientId})`);
        state.softGlow.setAttribute("filter", `url(#${softBlurId})`);
        state.coreGlow.setAttribute("fill", `url(#${gradientId})`);
        state.coreGlow.setAttribute("filter", `url(#${coreBlurId})`);
        state.worm.setAttribute("mask", `url(#${maskId})`);
    }

    function updateLoopState() {
        if (motionQuery.matches || activeCount === 0) {
            if (rafId) {
                window.cancelAnimationFrame(rafId);
                rafId = 0;
            }
            lastFrameTime = 0;
            return;
        }

        if (!rafId) {
            rafId = window.requestAnimationFrame(tick);
        }
    }

    function setActive(state, nextActive) {
        if (state.active === nextActive) return;

        state.active = nextActive;
        setWormVisible(state, nextActive && !motionQuery.matches);
        activeCount += nextActive ? 1 : -1;

        if (activeCount < 0) {
            activeCount = 0;
        }

        updateLoopState();
    }

    function updateGeometry(state) {
        const width = state.element.clientWidth;
        const height = state.element.clientHeight;

        if (!width || !height) {
            state.length = 0;
            return;
        }

        const inset = STROKE_WIDTH / 2;
        const rectWidth = Math.max(width - inset * 2, 0);
        const rectHeight = Math.max(height - inset * 2, 0);
        const radius = Math.max(rectHeight / 2, 0);

        state.svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
        state.rect.setAttribute("x", inset.toFixed(2));
        state.rect.setAttribute("y", inset.toFixed(2));
        state.rect.setAttribute("width", rectWidth.toFixed(2));
        state.rect.setAttribute("height", rectHeight.toFixed(2));
        state.rect.setAttribute("rx", radius.toFixed(2));
        state.rect.setAttribute("ry", radius.toFixed(2));

        if (state.maskPath) {
            state.maskPath.setAttribute("x", inset.toFixed(2));
            state.maskPath.setAttribute("y", inset.toFixed(2));
            state.maskPath.setAttribute("width", rectWidth.toFixed(2));
            state.maskPath.setAttribute("height", rectHeight.toFixed(2));
            state.maskPath.setAttribute("rx", radius.toFixed(2));
            state.maskPath.setAttribute("ry", radius.toFixed(2));
        }

        state.length = state.rect.getTotalLength();
    }

    function tick(timestamp) {

        if (motionQuery.matches || activeCount === 0) {
            rafId = 0;
            lastFrameTime = 0;
            return;
        }

        if (!lastFrameTime) {
            lastFrameTime = timestamp;
        }

        const deltaSeconds = (timestamp - lastFrameTime) / 1000;
        lastFrameTime = timestamp;

        for (const state of ctaStates) {

            if (!state.active || !state.length) continue;

            state.offset =
                (state.offset + SPEED_PX_PER_SECOND * deltaSeconds) % state.length;

            if (state.worm) {

                const point = state.rect.getPointAtLength(state.offset);

                const next = state.rect.getPointAtLength(
                    Math.min(state.offset + 1, state.length)
                );

                const angle =
                    Math.atan2(next.y - point.y, next.x - point.x) * 180 / Math.PI;

                state.worm.setAttribute(
                    "transform",
                    `translate(${point.x} ${point.y}) rotate(${angle})`
                );

            }

        }

        rafId = window.requestAnimationFrame(tick);

    }

    const visibilityObserver = new IntersectionObserver((entries) => {
        for (const entry of entries) {
            const state = ctaStateMap.get(entry.target);
            if (!state) continue;

            state.inView = entry.isIntersecting && entry.intersectionRatio > 0;
            setActive(state, state.inView && !motionQuery.matches);
        }
    }, {
        threshold: 0.01,
    });

    const resizeObserver = new ResizeObserver((entries) => {
        for (const entry of entries) {
            const state = ctaStateMap.get(entry.target);
            if (!state) continue;
            updateGeometry(state);
        }
    });

    function handleMotionChange() {
        for (const state of ctaStates) {
            if (motionQuery.matches) {
                setActive(state, false);
            } else {
                setActive(state, !!state.inView);
            }
        }
        updateLoopState();
    }

    function init() {
        const borders = document.querySelectorAll(CTA_SELECTOR);

        borders.forEach((element) => {
            const svg = element.querySelector(".cta-path-svg");
            const rect = element.querySelector(".cta-path");

            if (!svg || !rect) return;

            const state = {
                element,
                svg,
                rect,
                worm: svg.querySelector(".cta-worm"),
                softGlow: svg.querySelector(".cta-worm-soft"),
                coreGlow: svg.querySelector(".cta-worm-core"),
                gradient: svg.querySelector(".cta-worm-gradient"),
                softBlur: svg.querySelector(".cta-worm-soft-blur"),
                coreBlur: svg.querySelector(".cta-worm-core-blur"),
                mask: svg.querySelector(".cta-worm-mask"),
                maskPath: svg.querySelector(".cta-worm-mask-path"),

                length: 0,
                offset: 0,

                inView: false,
                active: false,
            };

            syncPaintServers(state, ctaStates.length);
            ctaStates.push(state);
            ctaStateMap.set(element, state);
            updateGeometry(state);
            state.offset = state.length ? (state.length * ((ctaStates.length * 0.173) % 1)) : 0;
            setWormVisible(state, false);
            resizeObserver.observe(element);
            visibilityObserver.observe(element);
        });

        handleMotionChange();
    }

    if (motionQuery.addEventListener) {
        motionQuery.addEventListener("change", handleMotionChange);
    } else if (motionQuery.addListener) {
        motionQuery.addListener(handleMotionChange);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
        init();
    }

    window.addEventListener("pagehide", () => {
        if (rafId) {
            window.cancelAnimationFrame(rafId);
        }
        visibilityObserver.disconnect();
        resizeObserver.disconnect();
    }, { once: true });
})();


