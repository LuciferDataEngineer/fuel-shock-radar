FROM apache/spark:3.5.3-python3

USER root
WORKDIR /opt/fuel
COPY src /opt/fuel/src
ENV PYTHONPATH=/opt/fuel/src \
    FUEL_SHOCK_SPARK_MODE=stream \
    KAFKA_BOOTSTRAP=redpanda:9092 \
    DELTA_ROOT=/data/delta

USER 185
ENTRYPOINT ["spark-submit"]
CMD ["--packages", "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.3,io.delta:delta-spark_2.12:3.2.1", "--conf", "spark.sql.extensions=io.delta.sql.DeltaSparkSessionExtension", "--conf", "spark.sql.catalog.spark_catalog=org.apache.spark.sql.delta.catalog.DeltaCatalog", "/opt/fuel/src/fuel_shock/spark_job.py"]
