import { APP_TIMEZONE } from "@/lib/app-timezone";

import type { ResearchPortfolioReport } from "@/lib/validation-types";

import { type ValidationPeriodDates } from "@/lib/validation-period";



export function formatValidationInstant(iso: string | null | undefined): string {

  if (!iso) {

    return "—";

  }

  const date = new Date(iso);

  if (Number.isNaN(date.getTime())) {

    return "—";

  }

  return date.toLocaleString("ru-RU", {

    timeZone: APP_TIMEZONE,

    day: "2-digit",

    month: "short",

    year: "numeric",

    hour: "2-digit",

    minute: "2-digit",

  });

}



export type ValidationSummaryBlock = {

  id: string;

  title: string;

  value: number;

  detail: string;

};



export function buildValidationSummaryBlocks(

  portfolio: ResearchPortfolioReport,

  dates: ValidationPeriodDates,

): ValidationSummaryBlock[] {

  const saved = portfolio.saved_in_period;

  const hasPeriod = Boolean(dates.from || dates.to);

  const newAnalyticalInPeriod =

    portfolio.observations.cohort_with_new_analytical_observation_in_period;



  const blocks: ValidationSummaryBlock[] = [

    {

      id: "saved",

      title: "Сохранено за период",

      value: saved.research_combined,

      detail: `${saved.videos} видео · ${saved.families} тем`,

    },

  ];



  if (hasPeriod && newAnalyticalInPeriod !== null && newAnalyticalInPeriod !== undefined) {

    blocks.push({

      id: "observations-in-period",

      title: "Получили новое наблюдение за период",

      value: newAnalyticalInPeriod,

      detail:
        "Все закладки (включая архив): повторное аналитическое измерение, не снимок при сохранении.",

    });

  } else {

    blocks.push({

      id: "observations-any",

      title: "Есть хотя бы одно наблюдение",

      value: portfolio.observations.cohort_with_any_observation,

      detail: "Среди объектов, сохранённых в выбранном интервале (не привязано к дате периода).",

    });

  }



  blocks.push({

    id: "decisions",

    title: "Смены вашего статуса за период",

    value: portfolio.decisions_in_period.status_changed_events,

    detail: "События status_changed по дате фиксации, не по дате сохранения.",

  });



  blocks.push({

    id: "no-feedback",

    title: "Без вашей оценки находки",

    value: portfolio.latest_feedback.cohort_without_latest_feedback,

    detail: "Оценка аналитика в карточке — отдельно от автоматических измерений Radar.",

  });



  return blocks;

}


