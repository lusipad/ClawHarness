FROM node:20-alpine AS source

ARG OPENCLAW_BOT_REVIEW_REPO=https://github.com/xmanrui/OpenClaw-bot-review.git
ARG OPENCLAW_BOT_REVIEW_REF=81deb042b5caecf109db9f7fa031b5063b671e20

RUN apk add --no-cache git
WORKDIR /src
RUN git clone "${OPENCLAW_BOT_REVIEW_REPO}" app && \
    cd app && \
    git checkout "${OPENCLAW_BOT_REVIEW_REF}"
COPY deploy/docker/openclaw-bot-view-overlay/ /overlay/
RUN cp -a /overlay/. /src/app/

FROM node:20-alpine AS deps
WORKDIR /app
COPY --from=source /src/app/package.json /src/app/package-lock.json ./
RUN npm ci

FROM deps AS build
WORKDIR /app
COPY --from=source /src/app ./
RUN npm run build

FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
ENV PORT=3000
ENV OPENCLAW_HOME=/opt/openclaw
COPY --from=build /app/package.json /app/package-lock.json ./
RUN npm ci --omit=dev
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["npm", "run", "start", "--", "-p", "3000", "-H", "0.0.0.0"]
