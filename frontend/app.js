let bookingId = "";
let verificationPassed = false;
let guestAgeCategories = [];

const primaryAge = document.getElementById("primaryAge");
const primaryUploads = document.getElementById("primaryUploads");
const guestCountInput = document.getElementById("guestCount");
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
const ACCEPTED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

function uploadError(file) {
  if (!ACCEPTED_IMAGE_TYPES.has(file.type)) return "Choose a JPG, PNG, or WEBP image.";
  if (file.size > MAX_UPLOAD_BYTES) return "Each image must be 5 MB or smaller.";
  return "";
}

primaryAge.addEventListener("change", () => {
  const needsProof = primaryAge.value === "5plus";
  primaryUploads.classList.toggle("hidden", !needsProof);
  document.getElementById("idFile").required = needsProof;
  document.getElementById("selfieFile").required = needsProof;
});

document.getElementById("idFile").addEventListener("change", function () {
  const file = this.files[0];
  const container = document.getElementById("idPreviewContainer");
  const preview = document.getElementById("idPreview");
  const message = document.getElementById("idFileMessage");
  container.classList.add("hidden");
  preview.src = "";
  message.textContent = "";
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    message.textContent = "Please select a valid image file.";
    this.value = "";
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    message.textContent = "ID image must be smaller than 5 MB.";
    this.value = "";
    return;
  }
  const reader = new FileReader();
  reader.onload = event => {
    preview.src = event.target.result;
    container.classList.remove("hidden");
    message.textContent = "ID image selected successfully.";
  };
  reader.readAsDataURL(file);
});

function showStep(n) {
  [1, 2, 3, 4].forEach(i => document.getElementById("step" + i).classList.toggle("hidden", i !== n));
  document.querySelectorAll(".progress span").forEach((span, i) => span.classList.toggle("active", i < n));
}

async function next(n) {
  bookingId = document.getElementById("booking").value.trim().toUpperCase();
  if (!bookingId) return alert("Enter a booking ID.");
  const button = document.querySelector("#step1 button");
  button.disabled = true;
  button.textContent = "Checking booking...";
  try {
    const response = await fetch("/api/booking/" + encodeURIComponent(bookingId));
    const data = await response.json();
    if (!response.ok) return alert(data.detail || "Booking not found.");
    document.getElementById("booking").value = data.booking_id;
    alert("Booking verified successfully!\n\nProperty: " + data.property_name);
    showStep(n);
  } catch (error) {
    console.error("Booking validation error:", error);
    alert("Could not verify the booking. Please make sure the server is running.");
  } finally {
    button.disabled = false;
    button.textContent = "Continue";
  }
}

async function continueToGuestDetails() {
  if (!primaryAge.value) return alert("Choose the primary guest’s age category.");
  if (primaryAge.value === "5plus") {
    const primaryId = document.getElementById("idFile").files[0];
    const primarySelfie = document.getElementById("selfieFile").files[0];
    if (primaryId && uploadError(primaryId)) return alert(`Primary guest ID: ${uploadError(primaryId)}`);
    if (primarySelfie && uploadError(primarySelfie)) return alert(`Primary guest selfie: ${uploadError(primarySelfie)}`);
    const ok = await runPrimaryVerification();
    if (!ok) return;
  } else {
    verificationPassed = true;
  }
  renderAdditionalGuests();
  showStep(3);
}

async function runPrimaryVerification() {
  const id = document.getElementById("idFile").files[0];
  const selfie = document.getElementById("selfieFile").files[0];
  if (!id || !selfie) {
    alert("For a primary guest aged 5 or older, select both a government ID image and a live selfie.");
    return false;
  }
  const message = document.getElementById("primaryVerifyMessage");
  message.textContent = "Running demo verification for the primary guest...";
  try {
    const ocrData = new FormData();
    ocrData.append("id_file", id);
    const ocrRes = await fetch("/api/ocr", { method: "POST", body: ocrData });
    const ocr = await ocrRes.json();
    document.getElementById("ocrResult").textContent = ocr.success
      ? "Demo ID check completed. Document details are not displayed."
      : "The synthetic ID image could not be read. Please try another demo image.";

    const faceData = new FormData();
    faceData.append("id_file", id);
    faceData.append("selfie", selfie);
    const faceRes = await fetch("/api/face-verify", { method: "POST", body: faceData });
    const face = await faceRes.json();
    const liveData = new FormData();
    liveData.append("selfie", selfie);
    const liveRes = await fetch("/api/liveness", { method: "POST", body: liveData });
    const live = await liveRes.json();

    document.getElementById("ocrCheck").textContent = ocr.success ? "✓ ID document processed" : "✗ ID processing failed";
    document.getElementById("faceCheck").textContent = face.match ? "✓ Face matched (demo)" : "✗ Face mismatch";
    document.getElementById("liveCheck").textContent = live.live ? "✓ Liveness passed (demo)" : "✗ Liveness failed";
    verificationPassed = !!(ocr.success && face.match && live.live);
    message.textContent = verificationPassed ? "Primary guest verification passed." : "Primary guest verification failed.";
    return verificationPassed;
  } catch (error) {
    console.error("Primary guest verification error:", error);
    message.textContent = "Could not complete primary guest verification. Check that the server is running.";
    return false;
  }
}

function renderAdditionalGuests() {
  const count = Number(guestCountInput.value);
  const host = document.getElementById("additionalGuests");
  host.replaceChildren();
  if (!Number.isInteger(count) || count < 1 || count > 20) return;
  for (let i = 2; i <= count; i++) {
    const card = document.createElement("fieldset");
    card.className = "guest-card";
    const legend = document.createElement("legend");
    legend.textContent = `Guest ${i}`;
    const label = document.createElement("label");
    label.htmlFor = `guestAge${i}`;
    label.textContent = "Age category";
    const select = document.createElement("select");
    select.id = `guestAge${i}`;
    select.dataset.guestIndex = String(i);
    select.innerHTML = '<option value="">Choose an age category</option><option value="under5">Under 5</option><option value="5plus">5 or older</option>';
    const uploads = document.createElement("div");
    uploads.id = `guestUploads${i}`;
    uploads.className = "hidden";
    const idLabel = document.createElement("label");
    idLabel.htmlFor = `guestId${i}`;
    idLabel.textContent = "Government ID image";
    const idFile = document.createElement("input");
    idFile.id = `guestId${i}`;
    idFile.type = "file";
    idFile.accept = "image/jpeg,image/png,image/webp";
    const selfieLabel = document.createElement("label");
    selfieLabel.htmlFor = `guestSelfie${i}`;
    selfieLabel.textContent = "Live selfie";
    const selfie = document.createElement("input");
    selfie.id = `guestSelfie${i}`;
    selfie.type = "file";
    selfie.accept = "image/jpeg,image/png,image/webp";
    selfie.capture = "user";
    select.addEventListener("change", () => {
      const required = select.value === "5plus";
      uploads.classList.toggle("hidden", !required);
      idFile.required = required;
      selfie.required = required;
    });
    uploads.append(idLabel, idFile, selfieLabel, selfie);
    card.append(legend, label, select, uploads);
    host.append(card);
  }
}

guestCountInput.addEventListener("input", renderAdditionalGuests);

async function completeVerification() {
  if (!verificationPassed) return alert("Complete primary guest verification first.");
  const name = document.getElementById("name").value.trim();
  const count = Number(guestCountInput.value);
  if (!name) return alert("Enter the primary guest’s name.");
  if (!Number.isInteger(count) || count < 1 || count > 20) return alert("Enter a guest count from 1 to 20.");
  const categories = [primaryAge.value];
  for (let i = 2; i <= count; i++) {
    const age = document.getElementById(`guestAge${i}`);
    if (!age || !age.value) return alert(`Choose an age category for Guest ${i}.`);
    categories.push(age.value);
    if (age.value === "5plus" && (!document.getElementById(`guestId${i}`).files[0] || !document.getElementById(`guestSelfie${i}`).files[0])) {
      return alert(`Guest ${i} is aged 5 or older. Select both a government ID image and a live selfie.`);
    }
  }
  guestAgeCategories = categories;
  const errorStatus = document.getElementById("groupError");
  errorStatus.classList.add("hidden");
  errorStatus.textContent = "";
  const payload = new FormData();
  payload.append("booking_id", bookingId);
  payload.append("name", name);
  payload.append("guest_count", String(count));
  payload.append("age_categories", JSON.stringify(categories));
  const adultIds = [];
  const adultSelfies = [];
  if (primaryAge.value === "5plus") {
    adultIds.push(document.getElementById("idFile").files[0]);
    adultSelfies.push(document.getElementById("selfieFile").files[0]);
  }
  for (let i = 2; i <= count; i++) {
    if (categories[i - 1] === "5plus") {
      adultIds.push(document.getElementById(`guestId${i}`).files[0]);
      adultSelfies.push(document.getElementById(`guestSelfie${i}`).files[0]);
    }
  }
  const adultGuestNumbers = categories
    .map((category, index) => category === "5plus" ? index + 1 : null)
    .filter(number => number !== null);
  const adultFiles = adultIds.map((file, index) => ({ file, label: `Guest ${adultGuestNumbers[index]} ID` }))
    .concat(adultSelfies.map((file, index) => ({ file, label: `Guest ${adultGuestNumbers[index]} selfie` })));
  for (const item of adultFiles) {
    const issue = uploadError(item.file);
    if (issue) {
      errorStatus.textContent = `${item.label}: ${issue}`;
      errorStatus.classList.remove("hidden");
      return;
    }
  }
  adultIds.forEach(file => payload.append("id_files", file));
  adultSelfies.forEach(file => payload.append("selfies", file));
  const generateButton = document.querySelector("#step3 button");
  generateButton.disabled = true;
  generateButton.textContent = "Verifying group...";
  try {
    const res = await fetch("/api/verify", {
      method: "POST",
      body: payload
    });
    const data = await res.json();
    if (!res.ok) {
      errorStatus.textContent = `Verification failed: ${data.detail || "Could not create pass."}`;
      errorStatus.classList.remove("hidden");
      return;
    }
    const qrResponse = await fetch("/api/qr/" + encodeURIComponent(data.token));
    const qr = await qrResponse.json();
    if (!qrResponse.ok) {
      errorStatus.textContent = `Pass created, but QR generation failed: ${qr.detail || "Please try again."}`;
      errorStatus.classList.remove("hidden");
      return;
    }
    document.getElementById("passName").textContent = data.name || name;
    document.getElementById("passBooking").textContent = data.booking_id || bookingId;
    document.getElementById("passCount").textContent = data.guest_count || count;
    document.getElementById("passVerifiedCount").textContent = data.verified_adult_count ?? 0;
    document.getElementById("passExemptCount").textContent = data.under5_count ?? 0;
    document.getElementById("passVerificationStatus").textContent = "Verified";
    document.getElementById("passStatus").textContent = "✓ GROUP VERIFIED";
    document.getElementById("token").textContent = "Token: " + data.token;
    document.getElementById("qr").src = qr.qr_data_url;
    showStep(4);
  } catch (error) {
    console.error("Guest pass error:", error);
    errorStatus.textContent = "Verification failed: Could not create the guest pass. Check that the server is running.";
    errorStatus.classList.remove("hidden");
  } finally {
    if (!document.getElementById("step3").classList.contains("hidden")) {
      generateButton.disabled = false;
      generateButton.textContent = "Confirm & Generate Guest Pass";
    }
  }
}
