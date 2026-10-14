"use strict";

const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
const initialServerTime = Date.parse(document.querySelector('meta[name="server-time"]')?.content || "");
let serverOffset = initialServerTime - Date.now();
const clockFormatter = new Intl.DateTimeFormat("id-ID", {timeZone: "Asia/Jakarta", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false});
const dateFormatter = new Intl.DateTimeFormat("id-ID", {timeZone: "Asia/Jakarta", weekday: "long", day: "numeric", month: "long", year: "numeric"});

function updateClock() {
    const current = new Date(Date.now() + serverOffset);
    if (Number.isNaN(current.getTime())) return;
    document.querySelectorAll("[data-live-clock]").forEach(element => { element.textContent = clockFormatter.format(current).replaceAll(".", ":"); });
    document.querySelectorAll("[data-live-date]").forEach(element => { element.textContent = dateFormatter.format(current); });
}
updateClock();
setInterval(updateClock, 1000);

document.querySelectorAll("[data-password-toggle]").forEach(button => {
    button.addEventListener("click", () => {
        const field = document.getElementById(button.dataset.passwordToggle);
        const show = field.type === "password";
        field.type = show ? "text" : "password";
        button.textContent = show ? "Tutup" : "Lihat";
        button.setAttribute("aria-label", show ? "Sembunyikan password" : "Tampilkan password");
    });
});
document.querySelectorAll("[data-dialog]").forEach(button => {
    button.addEventListener("click", () => document.getElementById(button.dataset.dialog).showModal());
});
document.querySelectorAll("[data-close-dialog]").forEach(button => {
    button.addEventListener("click", () => button.closest("dialog").close());
});
document.querySelectorAll("[data-go-back]").forEach(button => {
    button.addEventListener("click", () => { if (window.history.length > 1) window.history.back(); else window.location.assign("/"); });
});
document.querySelectorAll(".toast-close").forEach(button => {
    button.addEventListener("click", () => button.closest(".toast").remove());
});
document.querySelectorAll("form").forEach(form => {
    form.addEventListener("submit", event => {
        if (form.dataset.submitting === "true") { event.preventDefault(); return; }
        if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) { event.preventDefault(); return; }
        if (form.method.toLowerCase() !== "post") return;
        form.dataset.submitting = "true";
        form.setAttribute("aria-busy", "true");
        event.submitter?.classList.add("loading");
    });
});
window.addEventListener("pageshow", () => {
    document.querySelectorAll("form").forEach(form => {
        delete form.dataset.submitting;
        form.removeAttribute("aria-busy");
        form.querySelectorAll(".loading").forEach(element => element.classList.remove("loading"));
    });
});
const sidebarToggle = document.getElementById("sidebar-toggle");
const sidebarOverlay = document.getElementById("sidebar-overlay");
function toggleSidebar(open) {
    document.getElementById("sidebar")?.classList.toggle("is-open", open);
    sidebarToggle?.setAttribute("aria-expanded", String(open));
    if (sidebarOverlay) sidebarOverlay.hidden = !open;
}
sidebarToggle?.addEventListener("click", () => toggleSidebar(sidebarToggle.getAttribute("aria-expanded") !== "true"));
sidebarOverlay?.addEventListener("click", () => toggleSidebar(false));
document.addEventListener("keydown", event => { if (event.key === "Escape") toggleSidebar(false); });
requestAnimationFrame(() => document.querySelectorAll("[data-bar-height]").forEach(element => {
    element.style.height = Math.max(0, Math.min(100, Number(element.dataset.barHeight))) + "%";
}));

function getPosition() {
    return new Promise((resolve, reject) => {
        if (!window.isSecureContext || !navigator.geolocation) {
            reject(new Error("GPS memerlukan HTTPS atau localhost dan browser yang mendukung lokasi."));
            return;
        }
        navigator.geolocation.getCurrentPosition(resolve, error => {
            const explanations = {1: "Izin lokasi ditolak. Izinkan lokasi melalui pengaturan browser.", 2: "Lokasi tidak tersedia. Aktifkan GPS dan coba di area terbuka.", 3: "GPS belum merespons. Periksa sinyal lalu coba lagi."};
            reject(new Error(explanations[error.code] || "Lokasi tidak dapat diperiksa."));
        }, {enableHighAccuracy: true, timeout: 15000, maximumAge: 0});
    });
}

async function busy(button, callback) {
    if (button.dataset.busy === "true") return;
    const wasDisabled = button.disabled;
    button.dataset.busy = "true";
    button.classList.add("loading");
    button.disabled = true;
    try { return await callback(); }
    finally { delete button.dataset.busy; button.classList.remove("loading"); button.disabled = wasDisabled; }
}

document.getElementById("office-location-button")?.addEventListener("click", async event => {
    const status = document.getElementById("office-location-status");
    await busy(event.currentTarget, async () => {
        status.textContent = "Memeriksa posisi GPS...";
        try {
            const position = await getPosition();
            document.getElementById("office-latitude").value = position.coords.latitude.toFixed(7);
            document.getElementById("office-longitude").value = position.coords.longitude.toFixed(7);
            status.textContent = "Posisi terisi, akurasi " + position.coords.accuracy.toFixed(0) + " m. Periksa titik sebelum menyimpan kantor.";
        } catch (error) { status.textContent = error.message; }
    });
});

async function api(path, data) {
    const options = {credentials: "same-origin", headers: {"Accept": "application/json", "X-CSRF-Token": csrfToken}};
    if (data) { options.method = "POST"; options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(data); }
    const response = await fetch(path, options);
    if (!response.headers.get("Content-Type")?.includes("application/json")) throw new Error("Sesi berakhir atau layanan tidak tersedia. Muat ulang halaman dan login kembali.");
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.message || "Permintaan tidak berhasil.");
    return result;
}

function distanceMeters(latitude, longitude, officeLatitude, officeLongitude) {
    const radians = degrees => degrees * Math.PI / 180;
    const deltaLatitude = radians(officeLatitude - latitude);
    const deltaLongitude = radians(officeLongitude - longitude);
    const arc = Math.sin(deltaLatitude / 2) ** 2 + Math.cos(radians(latitude)) * Math.cos(radians(officeLatitude)) * Math.sin(deltaLongitude / 2) ** 2;
    return 6371000 * 2 * Math.atan2(Math.sqrt(Math.min(1, arc)), Math.sqrt(Math.max(0, 1 - arc)));
}

function setupAttendance() {
    const container = document.getElementById("attendance-app");
    if (!container) return;
    const office = JSON.parse(document.getElementById("office-data").textContent);
    if (!office || container.dataset.complete === "true") return;
    const startButton = document.getElementById("start-attendance");
    const captureButton = document.getElementById("capture-selfie");
    const submitButton = document.getElementById("submit-attendance");
    const refreshButton = document.getElementById("refresh-location");
    const video = document.getElementById("selfie-video");
    const preview = document.getElementById("selfie-preview");
    const canvas = document.getElementById("selfie-canvas");
    const placeholder = document.getElementById("camera-placeholder");
    const cameraLabel = document.getElementById("camera-label");
    const message = document.getElementById("attendance-message");
    const geofenceStatus = document.getElementById("geofence-status");
    const state = {position: null, valid: false, stream: null, selfie: null, challenge: null, capturedAt: 0, submitted: false};

    function showMessage(text, success = false) {
        message.textContent = text;
        message.className = "notice " + (success ? "notice-success" : "notice-danger");
        message.hidden = false;
    }
    function updateControls() {
        const fresh = state.position && Date.now() - state.position.timestamp <= 60000;
        captureButton.disabled = !state.valid || !fresh || !state.stream || state.submitted || captureButton.dataset.busy === "true";
        submitButton.disabled = !state.selfie || !state.challenge || !state.valid || !fresh || Date.now() - state.capturedAt > 120000 || state.submitted || submitButton.dataset.busy === "true";
    }
    function clearCapture() {
        state.selfie = null;
        state.challenge = null;
        state.capturedAt = 0;
        preview.hidden = true;
        preview.removeAttribute("src");
        video.hidden = !state.stream;
        placeholder.hidden = Boolean(state.stream);
        cameraLabel.textContent = state.stream ? "KAMERA DEPAN AKTIF" : "KAMERA BELUM AKTIF";
        updateControls();
    }
    function stopCamera() {
        state.stream?.getTracks().forEach(track => track.stop());
        state.stream = null;
        video.srcObject = null;
        video.hidden = true;
        updateControls();
    }
    async function locate() {
        clearCapture();
        state.valid = false;
        state.position = null;
        updateControls();
        geofenceStatus.className = "geofence-status";
        geofenceStatus.textContent = "Memeriksa GPS...";
        const position = await getPosition();
        state.position = position;
        const distance = distanceMeters(position.coords.latitude, position.coords.longitude, office.latitude, office.longitude);
        const accuracyOk = position.coords.accuracy > 0 && position.coords.accuracy <= office.max_accuracy_m;
        const inside = distance <= office.radius_m;
        state.valid = accuracyOk && inside;
        document.getElementById("gps-accuracy").textContent = position.coords.accuracy.toFixed(0) + " m";
        document.getElementById("gps-distance").textContent = distance.toFixed(0) + " m";
        document.getElementById("gps-coordinates").textContent = position.coords.latitude.toFixed(6) + ", " + position.coords.longitude.toFixed(6);
        geofenceStatus.className = "geofence-status " + (state.valid ? "valid" : "invalid");
        geofenceStatus.textContent = !accuracyOk ? "GPS kurang akurat; maksimal " + office.max_accuracy_m + " m." : (inside ? "Anda di dalam geofence." : "Di luar geofence; radius " + office.radius_m + " m.");
        updateControls();
        return position;
    }
    startButton.addEventListener("click", async () => {
        message.hidden = true;
        await busy(startButton, async () => {
            try {
                await locate();
                if (!navigator.mediaDevices?.getUserMedia) throw new Error("Kamera memerlukan HTTPS atau localhost dan browser yang mendukung MediaDevices.");
                if (!state.stream) {
                    state.stream = await navigator.mediaDevices.getUserMedia({audio: false, video: {facingMode: {ideal: "user"}, width: {ideal: 720}, height: {ideal: 720}}});
                    const facing = state.stream.getVideoTracks()[0].getSettings().facingMode;
                    if (facing && facing !== "user") { stopCamera(); throw new Error("Kamera depan tidak tersedia. Gunakan perangkat dengan kamera depan."); }
                    video.srcObject = state.stream;
                    video.hidden = false;
                    placeholder.hidden = true;
                    await video.play();
                    cameraLabel.textContent = "KAMERA DEPAN AKTIF";
                }
                if (!state.valid) showMessage("Lokasi belum memenuhi aturan. Perbarui GPS sebelum mengambil selfie.");
            } catch (error) { showMessage(error.name === "NotAllowedError" ? "Izin kamera ditolak. Izinkan kamera melalui pengaturan browser." : error.message); }
        });
        updateControls();
    });
    refreshButton.addEventListener("click", async () => {
        await busy(refreshButton, async () => {
            try { await locate(); message.hidden = true; }
            catch (error) { showMessage(error.message); geofenceStatus.textContent = "Lokasi belum tersedia."; }
        });
        updateControls();
    });
    captureButton.addEventListener("click", async () => {
        await busy(captureButton, async () => {
            try {
                await locate();
                if (!state.valid) throw new Error("GPS belum memenuhi geofence/akurasi. Perbarui lokasi lalu ulangi.");
                if (!state.stream || !video.videoWidth || !video.videoHeight) throw new Error("Kamera belum siap. Aktifkan kamera lalu ulangi.");
                const challenge = await api("/employee/attendance/challenge");
                if (challenge.action !== container.dataset.action) throw new Error("Status absensi berubah. Muat ulang halaman sebelum melanjutkan.");
                serverOffset = challenge.server_time - Date.now();
                if (Math.abs(serverOffset) > 300000) throw new Error("Jam perangkat berbeda lebih dari 5 menit. Aktifkan tanggal/jam otomatis.");
                canvas.width = 640;
                canvas.height = 640;
                const size = Math.min(video.videoWidth, video.videoHeight);
                canvas.getContext("2d").drawImage(video, (video.videoWidth - size) / 2, (video.videoHeight - size) / 2, size, size, 0, 0, 640, 640);
                const selfie = canvas.toDataURL("image/jpeg", 0.76);
                if (selfie.length * 0.75 > Number(container.dataset.maxPhotoBytes)) throw new Error("Selfie terlalu besar. Ambil ulang dengan pencahayaan yang baik.");
                state.selfie = selfie;
                state.challenge = challenge.challenge;
                state.capturedAt = Date.now();
                preview.src = selfie;
                preview.hidden = false;
                video.hidden = true;
                cameraLabel.textContent = "SELFIE SIAP DIKIRIM";
                captureButton.lastChild.textContent = " Ambil ulang";
                message.hidden = true;
            } catch (error) { clearCapture(); showMessage(error.message); }
        });
        updateControls();
    });
    submitButton.addEventListener("click", async () => {
        updateControls();
        if (submitButton.disabled) return;
        await busy(submitButton, async () => {
            try {
                const result = await api("/employee/attendance/submit", {action: container.dataset.action, challenge: state.challenge, latitude: state.position.coords.latitude, longitude: state.position.coords.longitude, accuracy: state.position.coords.accuracy, location_time: state.position.timestamp, device_time: Date.now(), selfie: state.selfie});
                state.submitted = true;
                stopCamera();
                showMessage(result.message, true);
                setTimeout(() => window.location.reload(), 1000);
            } catch (error) { clearCapture(); showMessage(error.message); }
        });
        updateControls();
    });
    setInterval(updateControls, 1000);
    window.addEventListener("pagehide", stopCamera);
    document.addEventListener("visibilitychange", () => {
        if (document.hidden) { stopCamera(); clearCapture(); state.position = null; state.valid = false; updateControls(); }
    });
}
setupAttendance();

document.querySelectorAll("[data-correction-form]").forEach(form => {
    const kind = form.querySelector("[data-correction-kind]");
    function updateCorrectionFields() {
        form.querySelectorAll("[data-correction-time]").forEach(input => {
            const applies = kind.value === "missing_attendance" ||
                (input.name === "check_in" ? kind.value === "check_in" : ["check_out", "missing_checkout"].includes(kind.value));
            input.disabled = !applies;
            input.required = applies;
        });
    }
    kind.addEventListener("change", updateCorrectionFields);
    updateCorrectionFields();
});
