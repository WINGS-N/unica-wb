FROM electronuserland/builder:wine

WORKDIR /project

RUN corepack enable && corepack prepare pnpm@10.6.2 --activate

ENTRYPOINT ["/bin/bash", "-lc"]
