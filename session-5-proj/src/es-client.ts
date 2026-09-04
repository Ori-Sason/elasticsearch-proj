import "dotenv/config";
import { Client } from "@elastic/elasticsearch";

export const INDEX_NAME = "logs-app";

export const esClient = new Client({
  node: process.env.ES_URL ?? "http://localhost:9200",
});
