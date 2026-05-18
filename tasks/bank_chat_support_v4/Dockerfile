FROM python:3.12-slim
RUN pip install --no-cache-dir \
    python-docx \
    reportlab \
    fpdf2 \
    openpyxl \
    pandas \
    markdown \
    weasyprint
WORKDIR /task
RUN mkdir -p /task/reference /task/output
