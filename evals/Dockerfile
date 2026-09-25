# The eval runner: Bun (no npm dependencies at run time) plus the docker CLI,
# which drives the host's daemon through the mounted socket to start one
# workspace container per run. Build context = this folder:
#
#   docker build -t atlas-evals evals/

FROM docker:29-cli AS docker-cli

FROM oven/bun:1.4-slim
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
WORKDIR /evals
COPY src ./src
COPY scenarios ./scenarios
ENTRYPOINT ["bun", "/evals/src/main.ts"]
