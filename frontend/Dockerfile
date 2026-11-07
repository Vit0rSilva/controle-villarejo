FROM controle-villarejo-villarejo-api:latest

ENV API_BACKEND_URL=http://villarejo-api:8000

EXPOSE 3000

CMD ["uvicorn", "frontend.server:frontend_app", "--host", "0.0.0.0", "--port", "3000"]
