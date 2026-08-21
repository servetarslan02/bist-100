FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install --legacy-peer-deps

COPY . .

RUN npm run build

# Standalone mode requires copying static files explicitly
RUN cp -r .next/static .next/standalone/.next/ && \
    (cp -r public .next/standalone/ 2>/dev/null || true)

EXPOSE 3000

ENV HOSTNAME="0.0.0.0"
ENV PORT=3000

# Run from the standalone directory
WORKDIR /app/.next/standalone
CMD ["node", "server.js"]
