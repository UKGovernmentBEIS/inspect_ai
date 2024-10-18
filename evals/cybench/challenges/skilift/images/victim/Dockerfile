# ------------------------------
# Build-Container
from debian:bookworm-slim as build

WORKDIR /app

COPY chall/Makefile .
COPY chall/sim_main.cpp .
COPY chall/top.v .

RUN DEBIAN_FRONTEND=noninteractive; \
    apt-get -y update; \
    apt-get -y install \
        make \
        g++ \
        verilator \
    ; \
    make verilator;

# ------------------------------
# Run-Container
FROM debian:bookworm-slim

WORKDIR /app

COPY --from=build /app/obj_dir/Vtop .

EXPOSE 1337

RUN DEBIAN_FRONTEND=noninteractive; \
    apt-get -y update; \
    apt-get -y install socat

CMD socat -T 60 \
    TCP-LISTEN:1337,nodelay,reuseaddr,fork \
    EXEC:"stdbuf -i0 -o0 -e0 /app/Vtop"