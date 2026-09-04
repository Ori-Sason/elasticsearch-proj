import { Router } from "express";
import { esClient, INDEX_NAME } from "../es-client.js";
import { handleEsError } from "../handle-es-error.js";

export const statsRouter = Router();

const VALID_INTERVALS = ["hour", "day", "week", "month"] as const;
type Interval = (typeof VALID_INTERVALS)[number];

function isValidInterval(value: string): value is Interval {
  return (VALID_INTERVALS as readonly string[]).includes(value);
}

// GET /stats?level=ERROR&interval=day
statsRouter.get("/stats", async (req, res) => {
  const { level, interval } = req.query;

  const filter: object[] = [];
  if (typeof level === "string" && level.length > 0) {
    filter.push({ term: { level } });
  }

  const calendarInterval: Interval =
    typeof interval === "string" && isValidInterval(interval) ? interval : "day";

  try {
    const result = await esClient.search({
      index: INDEX_NAME,
      size: 0,
      query: filter.length > 0 ? { bool: { filter } } : { match_all: {} },
      aggs: {
        by_service: {
          terms: { field: "service", size: 10 },
          aggs: {
            avg_status: { avg: { field: "status_code" } },
          },
        },
        logs_over_time: {
          date_histogram: {
            field: "timestamp",
            calendar_interval: calendarInterval,
          },
        },
      },
    });

    res.json(result.aggregations);
  } catch (err) {
    handleEsError(err, res);
  }
});
