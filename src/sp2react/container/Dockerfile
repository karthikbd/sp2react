# The image sp2react runs the generated app's back-end tests and loader in (pipeline.sandbox: container).
# Built once per change of the app's requirements.txt; the build context is the generated app's backend folder.
# The container itself runs with no network (or only the database host), a read-only file system, no
# capabilities and a non-root user; see sp2react/sandbox.py.
FROM python:3.12-slim

ARG EXTRA_PIP=""
ARG MSSQL=0
# Microsoft ODBC Driver 18, only for SQL Server through pyodbc (mssql+pyodbc:// URLs)
RUN if [ "$MSSQL" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends curl gnupg ca-certificates unixodbc && \
      curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg && \
      echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql.list && \
      apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 libgssapi-krb5-2 && \
      rm -rf /var/lib/apt/lists/*; \
    fi
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check -r /tmp/requirements.txt "pytest>=8" "httpx>=0.27" $EXTRA_PIP \
    && rm /tmp/requirements.txt
RUN useradd --create-home --uid 10001 check
USER 10001
