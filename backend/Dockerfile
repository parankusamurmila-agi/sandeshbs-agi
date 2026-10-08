FROM public.ecr.aws/lambda/python:3.12

# WeasyPrint (used for Word->PDF conversion) is pip-installable but still
# links these native shared libraries at runtime -- without them,
# doc_converter.convert_docx_to_pdf raises an OSError on import.
RUN dnf install -y pango cairo gdk-pixbuf2 harfbuzz-icu && dnf clean all

COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN python -m pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY app ${LAMBDA_TASK_ROOT}/app

CMD ["app.main.handler"]
