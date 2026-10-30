FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/package.json ./
COPY --from=build /app/.next ./.next
COPY --from=build /app/node_modules ./node_modules
# No COPY of ./public: this project has no public/
# directory, and Docker COPY fails when the source does
# not exist (Phase 9 audit: this broke `docker compose
# up --build` while local `npm run build` passed).
EXPOSE 3000
CMD ["npm", "start"]
