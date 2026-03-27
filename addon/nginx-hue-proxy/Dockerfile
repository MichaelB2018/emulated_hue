ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache nginx

COPY nginx.conf /etc/nginx/nginx.conf

RUN mkdir -p /run/nginx

COPY run.sh /etc/services.d/nginx/run
RUN chmod a+x /etc/services.d/nginx/run
