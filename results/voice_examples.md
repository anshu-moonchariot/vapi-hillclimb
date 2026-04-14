# Voice Call Examples — Baseline

**Baseline mean score**: 0.540 ± 0.378
**N calls**: 5
**Persona schedule**: ['simple_booking', 'reschedule', 'insurance_confused', 'impatient', 'bad_date']
**Assistant ID**: ec8c3cc2-e49f-49c2-9242-09cde84be6c0

---
## 1. Persona: simple_booking  (score=0.716)

**call_id**: 019d8b61-33bc-744c-8442-cbe7d05ad177
**stop_reason**: customer-ended-call
**turns**: 5
**structured_data**: {'procedure': 'routine teeth cleaning', 'contact_info': '5551234567', 'patient_name': 'Alex Johnson', 'appointment_date': 'Wednesday morning next week', 'appointment_booked': True}



---
## 2. Persona: reschedule  (score=0.025)

**call_id**: 019d8b62-f859-7771-b4df-36fc09b17edc
**stop_reason**: assistant-ended-call
**turns**: 2
**structured_data**: {'patient_name': 'Alex Johnson', 'appointment_booked': False}



---
## 3. Persona: insurance_confused  (score=0.149)

**call_id**: 019d8b63-c904-7ee0-bd46-9cd8427a7c9f
**stop_reason**: customer-ended-call
**turns**: 6
**structured_data**: {'procedure': 'teeth whitening', 'appointment_booked': False}



---
## 4. Persona: impatient  (score=0.904)

**call_id**: 019d8b65-47f4-7ff9-bcfc-f42daf27ac19
**stop_reason**: assistant-ended-call
**turns**: 4
**structured_data**: {'procedure': 'emergency', 'contact_info': '5551234', 'patient_name': 'Alex', 'appointment_date': 'today at 3 PM', 'appointment_booked': True}



---
## 5. Persona: bad_date  (score=0.904)

**call_id**: 019d8b66-cfdc-7ffc-b921-b08c193bbd7f
**stop_reason**: assistant-ended-call
**turns**: 4
**structured_data**: {'procedure': 'dental checkup', 'contact_info': '5551234', 'patient_name': 'Alex', 'appointment_date': 'Saturday at 10 AM', 'appointment_booked': True}


