from fastapi.testclient import TestClient
from main import app
import json

client = TestClient(app)

payload = {"to":"vamsiaratipamula@gmail.com","subject":"Professional Profile and Portfolio","body":"Dear Sir/Madam,\n\nI hope you are doing well. I am writing to share my professional background and portfolio for your consideration.\n\n**Current Role**\n- Program Analyst Trainee (GenC) at Cognizant, focusing on GCP & Google Workspace Technical Support (since June 25, 2026).\n\n**Previous Experience**\n- Intern → Full‑time at cmdOS (formerly Tasklabs), developing Chrome extensions.\n\n**Internship**\n- Cognizant internship (May 2026) with a focus on Google Cloud and Google Workspace.\n\n**Education**\n- B.Tech in Computer Science & Engineering, SRKR Engineering College, 2026.\n\nYou can view my work and credentials at the following links:\n- Resume: https://drive.google.com/file/d/18GAs_oVnNJH8fXZBEVu6m-FL5bMkI1NL/view?usp=drivesdk\n- GitHub: https://github.com/abvinnovator\n- LinkedIn: https://www.linkedin.com/in/brahmavamsi-aratipamula-42251626b\n- Personal website: https://brahmavamsia.netlify.app\n\nI am keen on opportunities in AI, full‑stack development, and system design. Please let me know if you need any further information.\n\nBest regards,\nBrahma Vamsi"}

# Ensure it works when we send it as JSON
response = client.post("/api/email/send", json=payload)
print("JSON response:", response.status_code, response.text)

# Also test sending it as a raw string bytes to mimic precisely OkHttp if it failed
raw_bytes = json.dumps(payload).encode('utf-8')
response = client.post("/api/email/send", content=raw_bytes, headers={"Content-Type": "application/json; charset=UTF-8"})
print("Raw bytes response:", response.status_code, response.text)

