from pathlib import Path
import uuid
import re
import pytesseract
import cv2
from PIL import Image

UPLOAD_DIR = Path(__file__).parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

def save_upload(upload_file):
    suffix = ALLOWED_IMAGE_TYPES.get(upload_file.content_type)
    if not suffix:
        raise ValueError("Upload must be a JPG, PNG, or WEBP image.")
    content = upload_file.file.read(MAX_UPLOAD_BYTES + 1)
    if not content:
        raise ValueError("Uploaded image is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("Each uploaded image must be 5 MB or smaller.")
    name = f"{uuid.uuid4().hex}{suffix}"
    path = UPLOAD_DIR / name
    with open(path, "wb") as f:
        f.write(content)
    return str(path)

def demo_ocr(filename: str):
    try:
        # --------------------------------
        # LOAD IMAGE
        # --------------------------------

        image = cv2.imread(filename)

        if image is None:
            return {
                "success": False,
                "document_type": "Unknown",
                "name": "",
                "date_of_birth": "",
                "gender": "",
                "document_number": "",
                "expiry": "",
                "raw_text": "",
                "message": "Could not open the uploaded image."
            }

        # --------------------------------
        # RESIZE
        # --------------------------------

        height, width = image.shape[:2]

        if width < 1800:
            scale = 1800 / width

            image = cv2.resize(
                image,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_CUBIC
            )

        # --------------------------------
        # CREATE MULTIPLE OCR VERSIONS
        # --------------------------------

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Improve contrast
        enhanced = cv2.equalizeHist(gray)

        # Threshold version
        threshold = cv2.threshold(
            enhanced,
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )[1]

        # --------------------------------
        # RUN TESSERACT ON MULTIPLE VERSIONS
        # --------------------------------

        ocr_results = []

        # Original colour image
        text_original = pytesseract.image_to_string(
            image,
            config="--psm 6"
        )

        if text_original.strip():
            ocr_results.append(text_original)

        # Grayscale image
        text_gray = pytesseract.image_to_string(
            gray,
            config="--psm 6"
        )

        if text_gray.strip():
            ocr_results.append(text_gray)

        # Enhanced image
        text_enhanced = pytesseract.image_to_string(
            enhanced,
            config="--psm 6"
        )

        if text_enhanced.strip():
            ocr_results.append(text_enhanced)

        # Threshold image
        text_threshold = pytesseract.image_to_string(
            threshold,
            config="--psm 6"
        )

        if text_threshold.strip():
            ocr_results.append(text_threshold)

        # --------------------------------
        # COMBINE OCR RESULTS
        # --------------------------------

        if not ocr_results:
            return {
                "success": False,
                "document_type": "Unknown",
                "name": "",
                "date_of_birth": "",
                "gender": "",
                "document_number": "",
                "expiry": "",
                "raw_text": "",
                "message": "Tesseract could not detect readable text."
            }

        combined_text = "\n".join(ocr_results)

        # Remove duplicate empty lines
        lines = [
            line.strip()
            for line in combined_text.splitlines()
            if line.strip()
        ]

        clean_text = "\n".join(lines)
        upper_text = clean_text.upper()

        # --------------------------------
        # AADHAAR DETECTION
        # --------------------------------

        aadhaar_keywords = [
            "AADHAAR",
            "AADHAR",
            "आधार",
            "UNIQUE IDENTIFICATION",
            "GOVERNMENT OF INDIA"
        ]

        is_aadhaar = any(
            keyword in upper_text
            for keyword in aadhaar_keywords
        )

        document_type = "Aadhaar" if is_aadhaar else "Government ID"

                # --------------------------------
        # NAME DETECTION
        # --------------------------------

        name = ""

        # First try a clearly labelled name.
        name_patterns = [
            r"(?:NAME|FULL NAME|SAME|SANE)\s*[:\-]?\s*([A-Za-z][A-Za-z .'-]{2,})"
        ]

        for pattern in name_patterns:

            match = re.search(
                pattern,
                clean_text,
                re.IGNORECASE
            )

            if match:
                name = match.group(1).strip()
                break

        # --------------------------------
        # AADHAAR NAME FROM DOB CONTEXT
        # --------------------------------
        #
        # Many Aadhaar layouts place the person's
        # name immediately before the DOB line.
        #
        # Example:
        #
        # RAHUL KUMAR
        # DOB: 15-08-1994
        #
        # or:
        #
        # Niranjan Kumar
        # DOB: 12/04/2000
        #

        if not name and is_aadhaar:

            for index, line in enumerate(lines):

                upper_line = line.upper()

                # Look for a DOB line.
                if (
                    "DOB" in upper_line
                    or "D.O.B" in upper_line
                    or "DATE OF BIRTH" in upper_line
                ):

                    # Check the line immediately before DOB.
                    if index > 0:

                        candidate = lines[index - 1].strip()

                        # Remove OCR characters before the name.
                        candidate = re.sub(
                            r"^[^A-Za-z]+",
                            "",
                            candidate
                        ).strip()

                        # Remove OCR characters after the name.
                        candidate = re.sub(
                            r"[^A-Za-z .'-]+$",
                            "",
                            candidate
                        ).strip()

                        # Make sure it doesn't contain numbers.
                        if not re.search(r"\d", candidate):

                            # Make sure it looks like a person's name.
                            if re.fullmatch(
                                r"[A-Za-z][A-Za-z .'-]{2,}",
                                candidate
                            ):

                                words = candidate.split()

                                if 2 <= len(words) <= 4:

                                    name = candidate.title()
                                    break

        # --------------------------------
        # FALLBACK NAME DETECTION
        # --------------------------------

        if not name:

            ignored_words = {
                "GOVERNMENT",
                "INDIA",
                "AADHAAR",
                "AADHAR",
                "IDENTIFICATION",
                "UNIQUE",
                "AUTHORITY",
                "MALE",
                "FEMALE",
                "TRANSGENDER",
                "DOB",
                "D.O.B",
                "DATE",
                "BIRTH",
                "YEAR",
                "ADDRESS",
                "ENROLMENT",
                "ENROLLMENT",
                "VID",
                "GENDER",
                "CARD",
                "BANK"
            }

            candidates = []

            for line in lines:

                candidate = line.strip()

                # Remove OCR garbage before the name.
                candidate = re.sub(
                    r"^[^A-Za-z]+",
                    "",
                    candidate
                ).strip()

                # Remove OCR garbage after the name.
                candidate = re.sub(
                    r"[^A-Za-z .'-]+$",
                    "",
                    candidate
                ).strip()

                # Ignore numbers.
                if re.search(r"\d", candidate):
                    continue

                if len(candidate) < 5:
                    continue

                upper_candidate = candidate.upper()

                if upper_candidate in ignored_words:
                    continue

                if any(
                    upper_candidate.startswith(word)
                    for word in [
                        "GOVERNMENT",
                        "AADHAAR",
                        "AADHAR",
                        "IDENTIFICATION",
                        "UNIQUE",
                        "AUTHORITY",
                        "GENDER",
                        "DOB",
                        "DATE",
                        "ADDRESS",
                        "ENROLMENT",
                        "ENROLLMENT"
                    ]
                ):
                    continue

                if not re.fullmatch(
                    r"[A-Za-z][A-Za-z .'-]{2,}",
                    candidate
                ):
                    continue

                words = candidate.split()

                if 2 <= len(words) <= 4:

                    normalized = re.sub(
                        r"[^a-z]",
                        "",
                        candidate.lower()
                    )

                    candidates.append(
                        (candidate, normalized)
                    )

            # Count repeated candidates.
            candidate_scores = {}

            for candidate, normalized in candidates:

                if normalized not in candidate_scores:

                    candidate_scores[normalized] = {
                        "text": candidate,
                        "count": 0
                    }

                candidate_scores[normalized]["count"] += 1

            if candidate_scores:

                best = max(
                    candidate_scores.values(),
                    key=lambda item: item["count"]
                )

                name = best["text"].title()

        # --------------------------------
        # DATE OF BIRTH
        # --------------------------------

        date_of_birth = ""

        dob_patterns = [
            r"(?:DOB|D\.O\.B|DATE OF BIRTH|BIRTH)\s*[:\-]?\s*(\d{2}[/-]\d{2}[/-]\d{4})",
            r"(?:DOB|D\.O\.B|DATE OF BIRTH|BIRTH)\s*[:\-]?\s*(\d{2}\.\d{2}\.\d{4})"
        ]

        for pattern in dob_patterns:

            match = re.search(
                pattern,
                clean_text,
                re.IGNORECASE
            )

            if match:
                date_of_birth = match.group(1)
                break

        # If DOB label was not detected,
        # search all normal date formats.
        if not date_of_birth:

            date_matches = re.findall(
                r"\b\d{2}[/-]\d{2}[/-]\d{4}\b",
                clean_text
            )

            if date_matches:
                date_of_birth = date_matches[0]

        # --------------------------------
        # GENDER
        # --------------------------------

        gender = ""

        gender_match = re.search(
            r"\b(MALE|FEMALE|TRANSGENDER)\b",
            upper_text
        )

        if gender_match:
            gender = gender_match.group(1).title()

        # --------------------------------
        # AADHAAR NUMBER
        # --------------------------------

        document_number = ""

        aadhaar_patterns = [
            r"(?<!\d)\d{4}\s+\d{4}\s+\d{4}(?!\d)",
            r"(?<!\d)\d{12}(?!\d)"
        ]

        for pattern in aadhaar_patterns:

            match = re.search(
                pattern,
                clean_text
            )

            if match:
                document_number = match.group(0)

                document_number = re.sub(
                    r"\s+",
                    " ",
                    document_number
                ).strip()

                break

        # --------------------------------
        # RESULT
        # --------------------------------

        return {
            "success": True,
            "document_type": document_type,
            "name": name,
            "date_of_birth": date_of_birth,
            "gender": gender,
            "document_number": document_number,
            "expiry": "",
            "raw_text": clean_text,
            "message": "OCR completed using Tesseract and OpenCV."
        }

    except Exception as e:

        return {
            "success": False,
            "document_type": "Unknown",
            "name": "",
            "date_of_birth": "",
            "gender": "",
            "document_number": "",
            "expiry": "",
            "raw_text": "",
            "message": f"OCR error: {str(e)}"
        }

def demo_face_verify(id_file: str, selfie_file: str):
    # DEMO ONLY: always returns a passing result.
    # Replace with a real face verification service.
    return {
        "success": True,
        "match": True,
        "similarity": 0.97,
        "message": "Demo face match. No biometric verification was performed."
    }

def demo_liveness(selfie_file: str):
    # DEMO ONLY: not real liveness detection.
    return {
        "success": True,
        "live": True,
        "confidence": 0.95,
        "message": "Demo liveness result. Replace with a dedicated liveness system."
    }

def sanitize_name(value: str):
    value = re.sub(r"[^a-zA-Z0-9 .'-]", "", value or "")
    return value.strip()[:80]
