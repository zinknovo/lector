FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /workspace
COPY lector-api/pom.xml /workspace/pom.xml
RUN mvn -q -DskipTests dependency:go-offline
COPY lector-api/src /workspace/src
RUN mvn -q package -DskipTests

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /workspace/target/lector-api-0.1.0.jar /app/lector-api.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/lector-api.jar"]
