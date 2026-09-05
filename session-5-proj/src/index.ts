import "dotenv/config";
import express from "express";
import { searchRouter } from "./routes/search.js";
import { statsRouter } from "./routes/stats.js";
import { logsRouter } from "./routes/logs.js";

const app = express();

app.use(express.json());
app.use(searchRouter);
app.use(statsRouter);
app.use(logsRouter);

const port = +(process.env.PORT ?? 3000);
app.listen(port, () => {
  console.log(`API listening on http://localhost:${port}`);
});
