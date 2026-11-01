# willow's review of the seed corpus, 2026-11-01

The seed was read through willow's new `jeles` add-on, which mirrors Jeles seed files and corpus stores as passages, then checked with willow's own tools. Nothing in the seed was changed by this review.

## What was read

- `jeles.py mirror` read **82 of the 87 seed files**. The 5 it skipped (`adv_challenge-ai`, `adv_challenge-modern`, `adv_steelman-historical`, `adv_steelman-modern`, `adv_steelman-tech`) hold adversarial reasoning (challenges and steelmen), not question-and-answer pairs. `seed_loader` treats them the same way: reasoning about claims, not claims.

## Internal contradictions: none to fix

willow's `contradictions` (two passages disagreeing about the same date or amount) flagged 11 pairs across the seed. All 11 were read, and none is a real contradiction:

- **Unrelated passages:** most pair passages that only share words. For example, "Agriculture uses 70% of the world's freshwater" against a passage about endangered languages.
- **By design:** the Amazon "20% of the world's oxygen" claim appears only as the target of `adv2_factcheck-r8`, which refutes it. That is the adversarial rounds working.
- **Agreement:** `r9_health-medicine`'s "over 5,000%" and "5,455%" for Daraprim's 2015 price rise are consistent with each other.

## Duplicates: by design

willow's `duplicates` found 194 lines of passages that say the same thing in two files. They are the adversarial rounds (`adv2_*`, `adv3_*`) quoting, word for word, the claims they challenge from the `r8_*` and `r9_*` files. That is how the rounds are built, so there is nothing to merge.

## Citations: 150 don't answer

Every URL the seed cites, in pairs' `evidence_urls` and in files' `evidence` locators, was probed once with a browser User-Agent: **1783 distinct URLs**.

| result | URLs | reading |
|---|---|---|
| 200 | 1105 | answers |
| 403, 401, 406, 429, 202 | 518 | mostly bot protection or rate limits; unverified, not dead |
| 404 | 115 | the page isn't there |
| no answer | 35 | DNS failure, timeout or refused connection |
| other (5xx, 400, 402, 405, 520) | 10 | server errors; worth a second try |

For the 150 that 404 or don't answer, the Wayback Machine's availability API was asked for an archived copy. **44 have one.**

### Why they aren't replaced automatically

A commons pair's credit is computed from its citations: `jeles.commons` reads `verified_by` as "public record: <publishers>" from the cited hosts. Swapping a dead URL for its `web.archive.org` copy would credit the Internet Archive as the publisher. Each one needs a curator's call:

- the publisher's new address, if the page moved; or
- the archived copy kept beside the original, once `commons` knows to credit the original host for an archive URL; or
- a different source.

### By seed file

Status, the URL, and the archived copy where there is one.

**adv2_challenge-r8.json**

- 404 https://noyb.eu/en/5-years-gdpr-report
- 404 https://www.brookings.edu/articles/why-does-piketty-capital-in-the-twenty-first-century-still-matter/
- 404 https://www.ftc.gov/reports/consumer-sentinel-network-data-book-2022 · [archived 2026-08-21](http://web.archive.org/web/20260821202843/https://www.ftc.gov/reports/consumer-sentinel-network-data-book-2022)

**adv2_factcheck-r8.json**

- 404 https://www.eci.ox.ac.uk/research/ecodynamics/ymalhi.html
- 404 https://www.supremecourt.gov/opinions/09pdf/08-205.pdf · [archived 2025-09-15](http://web.archive.org/web/20250915101323/https://www.supremecourt.gov/opinions/09pdf/08-205.pdf)

**adv2_steelman-r8.json**

- no answer https://bitcoinminingcouncil.com/wp-content/uploads/2024/01/BMC-Q4-2023-Briefing.pdf
- 404 https://econpapers.repec.org/article/aborevam1/v_3a3_3ay_3a2015_3ai_3a2_3ap_3a137-163.htm
- 404 https://thearmstradetreaty.org/treaty-status.html · [archived 2026-04-07](http://web.archive.org/web/20260407202605/https://thearmstradetreaty.org/treaty-status.html)
- 404 https://www.chainalysis.com/blog/sub-saharan-africa-cryptocurrency-geography-of-cryptocurrency-2022/
- no answer https://www.pclob.gov/library/702-Report.pdf · [archived 2020-05-15](http://web.archive.org/web/20200515190032/https://www.pclob.gov/library/702-Report.pdf)

**adv3_factcheck-r9.json**

- 404 https://aspe.hhs.gov/topics/poverty-economic-mobility/negative-income-tax-experiments-1960s-1970s
- 404 https://www.fda.gov/news-events/press-announcements/fda-declines-approve-mdma-assisted-therapy-ptsd
- no answer https://www.mckinsey.com/featured-insights/future-of-work/jobs-lost-jobs-gained-what-the-future-of-work-will-mean-for-jobs-skills-and-wages · [archived 2026-08-14](http://web.archive.org/web/20260814151500/https://www.mckinsey.com/featured-insights/future-of-work/jobs-lost-jobs-gained-what-the-future-of-work-will-mean-for-jobs-skills-and-wages)

**adv3_steelman-r9.json**

- no answer https://www.alltrials.net/ · [archived 2025-08-17](http://web.archive.org/web/20250817122533/http://www.alltrials.net/)
- 404 https://www.cjr.org/special_report/what-went-wrong-iraq-war-media.php
- 404 https://www.justice.gov/usao-edmi/uaw
- no answer https://www.mckinsey.com/featured-insights/future-of-work/jobs-lost-jobs-gained-what-the-future-of-work-will-mean-for-jobs-skills-and-wages · [archived 2026-08-14](http://web.archive.org/web/20260814151500/https://www.mckinsey.com/featured-insights/future-of-work/jobs-lost-jobs-gained-what-the-future-of-work-will-mean-for-jobs-skills-and-wages)
- no answer https://www.mckinsey.com/featured-insights/sustainable-inclusive-growth/future-of-america/american-opportunity-survey · [archived 2026-07-13](http://web.archive.org/web/20260713161735/https://www.mckinsey.com/featured-insights/sustainable-inclusive-growth/future-of-america/american-opportunity-survey)
- 404 https://www.sos.ca.gov/elections/ballot-measures/qualified-ballot-measures/proposition-22
- 404 https://www.theguardian.com/film/2022/may/25/val-kilmer-top-gun-maverick-ai-voice

**adv_factcheck-historical.json**

- 404 https://www.newtonproject.ox.ac.uk/his-life
- 404 https://www.theartnewspaper.com/2019/11/01/did-van-gogh-really-only-sell-one-painting-during-his-lifetime
- 404 https://www.vangoghmuseum.nl/en/art-and-stories/stories/van-goghs-earnings
- 404 https://www.vanityfair.com/culture/2012/02/qatar-buys-cezanne-card-players

**adv_steelman-tech.json**

- no answer https://dissidentvoice.org/2023/05/geoffrey-hinton-ai-and-googles-ethics-problem/ · [archived 2025-12-10](http://web.archive.org/web/20251210080452/https://dissidentvoice.org/2023/05/geoffrey-hinton-ai-and-googles-ethics-problem/)

**conv_adv_steelman-historical.json**

- 404 https://archive.org/details/karlmarxcloseohi00bohm
- 404 https://www.penguinrandomhouse.com/books/292025/the-coming-of-the-third-reich-by-richard-j-evans/
- 404 https://www.penguinrandomhouse.com/books/78543/stalin-by-stephen-kotkin/
- 404 https://www.penguinrandomhouse.com/books/98218/picasso-by-marina-picasso/
- 404 https://www.versobooks.com/products/1126-marx-after-sraffa

**conv_adv_steelman-modern.json**

- 404 https://intelligence.house.gov/news/documentsingle.aspx?DocumentID=780 · [archived 2025-06-06](http://web.archive.org/web/20250606161958/https://intelligence.house.gov/news/documentsingle.aspx?DocumentID=780)
- 404 https://journalistsresource.org/politics-and-government/digital-activism-slacktivism-research/
- no answer https://ncrb.gov.in/accidental-deaths-suicides-in-india.html
- 404 https://www.archives.gov/iwg/research-papers/paperclip-war-crimes
- 404 https://www.ben-evans.com/benedictevans/2021/10/4/facebook-and-the-metaverse
- 404 https://www.cnn.com/2019/09/18/politics/ruth-bader-ginsburg-retirement/index.html
- 404 https://www.justice.gov/civil/pages/attachments/2024/10/24/fca_stats.pdf
- 404 https://www.penguinrandomhouse.com/books/292090/von-braun-by-michael-j-neufeld/
- no answer https://www.washingtonpost.com/archive/politics/2000/11/02/nader-runs-hard-in-close-states/

**conv_adv_steelman-tech.json**

- no answer https://dissidentvoice.org/2023/05/geoffrey-hinton-ai-and-googles-ethics-problem/ · [archived 2025-12-10](http://web.archive.org/web/20251210080452/https://dissidentvoice.org/2023/05/geoffrey-hinton-ai-and-googles-ethics-problem/)

**core_arts-music.json**

- no answer https://people.carleton.edu/~jellinge/m101s12/Pages/03/03bSimpleMeter.html · [archived 2025-07-01](http://web.archive.org/web/20250701160554/https://people.carleton.edu/~jellinge/m101s12/Pages/03/03bSimpleMeter.html)

**core_digital-communication.json**

- 404 https://www.wired.com/story/the-science-of-autocorrect/

**core_electricity-home.json**

- 404 https://www.energy.gov/energysaver/central-air-conditioning · [archived 2026-06-14](http://web.archive.org/web/20260614012130/https://www.energy.gov/energysaver/central-air-conditioning)
- 404 https://www.energy.gov/energysaver/electrical-distribution-and-safety
- 404 https://www.energy.gov/energysaver/refrigerator-and-freezer
- 404 https://www.energy.gov/energysaver/water-heating · [archived 2026-07-02](http://web.archive.org/web/20260702050136/https://www.energy.gov/energysaver/water-heating)
- 404 https://www.nfpa.org/education-and-research/home-safety/smoke-alarms
- 404 https://www.osha.gov/electrical/grounding

**core_food-body.json**

- 404 https://www.acsm.org/blog-detail/acsm-blog/2019/10/01/delayed-onset-muscle-soreness-doms
- 404 https://www.exploratorium.edu/cooking/eggs/eggscience.html · [archived 2023-04-07](http://web.archive.org/web/20230407033441/https://www.exploratorium.edu/cooking/eggs/eggscience.html)
- 404 https://www.kingarthurbaking.com/blog/2017/04/07/how-yeast-works
- 404 https://www.scienceofcooking.com/how_does_salt_preserve_food.htm

**core_heat-light-sound.json**

- 404 https://www.energy.gov/energysaver/insulation · [archived 2026-06-22](http://web.archive.org/web/20260622043413/https://www.energy.gov/energysaver/insulation)
- 404 https://www.scientificamerican.com/article/why-does-metal-feel-cold/

**core_materials-chemistry.json**

- 404 https://www.americanchemistry.com/chemistry-in-america/news-trends/blog-post/2020/the-science-of-corrosion
- 404 https://www.compoundchem.com/2014/04/29/the-chemistry-of-stain-removal/
- 404 https://www.sciencehistory.org/education/classroom-activities/the-history-and-future-of-plastics/

**core_measurement-time.json**

- 404 https://www.nist.gov/pml/owm/metric-si/si-history
- 404 https://www.scientificamerican.com/article/why-is-a-minute-divided-into-60-seconds/

**core_money-society.json**

- 404 https://bja.ojp.gov/program/plea-bargaining/overview
- 404 https://www.eac.gov/voters/how-to-vote
- 404 https://www.federalreserve.gov/publications/2023-economic-well-being-of-us-households-in-2022-banking-and-credit.htm
- 404 https://www.irs.gov/newsroom/irs-provides-tax-inflation-adjustments-for-tax-year-2025

**core_transportation.json**

- 404 https://www.energy.gov/eere/vehicles/articles/electric-car-basics
- 404 https://www.gps.gov/systems/gps/performance/accuracy/ · [archived 2025-09-02](http://web.archive.org/web/20250902224834/https://www.gps.gov/systems/gps/performance/accuracy/)
- no answer https://www.railway-technical.com/trains/rolling-stock/wheels/
- 404 https://www.worldshipping.org/about-the-industry/history-of-containerization · [archived 2021-05-11](http://web.archive.org/web/20210511112406/https://www.worldshipping.org/about-the-industry/history-of-containerization)

**core_weather-earth.json**

- 404 https://science.nasa.gov/resource/why-earth-has-seasons/
- no answer https://scijinks.gov/rainbow/
- 404 https://www.noaa.gov/education/resource-collections/weather-atmosphere/water-cycle
- 404 https://www.noaa.gov/jetstream/fog
- 404 https://www.noaa.gov/jetstream/wind
- 404 https://www.nps.gov/subjects/caves/cave-formation.htm
- no answer https://www.nrcs.usda.gov/conservation-basics/natural-resource-concerns/soils
- 404 https://www.usgs.gov/programs/volcano-hazards/about-volcanoes
- 404 https://www.usgs.gov/special-topics/fossils

**core_world-history.json**

- no answer https://beyond.britannica.com/can-you-provide-a-timeline-chronology-of-the-origins-beginnings-of-the-top-10-living-surviving-religions-of-the-world · [archived 2022-06-30](http://web.archive.org/web/20220630075411/https://beyond.britannica.com/can-you-provide-a-timeline-chronology-of-the-origins-beginnings-of-the-top-10-living-surviving-religions-of-the-world)

**hist_liberation.json**

- no answer https://crgreview.com/the-power-of-african-activism-how-the-anc-and-umkhonto-we-sizwe-defeated-apartheid/ · [archived 2026-05-10](http://web.archive.org/web/20260510055037/https://crgreview.com/the-power-of-african-activism-how-the-anc-and-umkhonto-we-sizwe-defeated-apartheid/)
- no answer https://icnacsj.org/the-sanitization-of-martin-luther-king-jr-s-legacy/ · [archived 2024-12-26](http://web.archive.org/web/20241226231601/https://icnacsj.org/the-sanitization-of-martin-luther-king-jr-s-legacy/)
- no answer https://www.theoldie.co.uk/blog/the-pankhursts-at-war

**mw_cities-infrastructure.json**

- no answer https://cms7.fta.dot.gov/research-innovation/bus-rapid-transit · [archived 2021-05-07](http://web.archive.org/web/20210507031918/https://cms7.fta.dot.gov/research-innovation/bus-rapid-transit)

**mw_energy-grids.json**

- no answer https://formenergy.com/form-energy-crusoe-announce-agreement-for-12-gigawatt-hours-of-iron-air-batteries-for-ai-data-centers/ · [archived 2026-08-29](http://web.archive.org/web/20260829185008/https://formenergy.com/form-energy-crusoe-announce-agreement-for-12-gigawatt-hours-of-iron-air-batteries-for-ai-data-centers/)
- no answer https://howtostoreelectricity.com/renewable-curtailment/
- no answer https://insidelines.pjm.com/2025-in-review-pjm-market-rules-support-efficiency-resource-adequacy/ · [archived 2026-03-02](http://web.archive.org/web/20260302213501/https://insidelines.pjm.com/2025-in-review-pjm-market-rules-support-efficiency-resource-adequacy/)

**mw_healthcare-systems.json**

- no answer https://hospitalmedicaldirector.com/operating-room-block-scheduling-versus-open-scheduling/ · [archived 2026-10-20](http://web.archive.org/web/20261020175440/https://hospitalmedicaldirector.com/operating-room-block-scheduling-versus-open-scheduling/)

**mw_internet-infrastructure.json**

- no answer https://netrality.com/blog/internet-exchange-points-ixp-network-peering/ · [archived 2026-04-06](http://web.archive.org/web/20260406155016/https://netrality.com/blog/internet-exchange-points-ixp-network-peering/)

**ppl_infrastructure-builders.json**

- no answer https://www.washingtonpost.com/politics/2021/11/10/robert-moses-saga-racist-parkway-bridges/ · [archived 2025-07-22](http://web.archive.org/web/20250722070424/https://www.washingtonpost.com/politics/2021/11/10/robert-moses-saga-racist-parkway-bridges/)

**ppl_media-shapers.json**

- no answer https://www.washingtonpost.com/opinions/2024/10/29/bezos-editorial-washington-post/

**ppl_open-source.json**

- no answer https://byteiota.com/open-source-maintainer-crisis-60-unpaid-burnout-hits-44/ · [archived 2026-06-23](http://web.archive.org/web/20260623045451/https://byteiota.com/open-source-maintainer-crisis-60-unpaid-burnout-hits-44/)
- 404 https://theregister.com/AMP/2024/02/09/opinion_column_mozilla_ceo_quits · [archived 2025-07-08](http://web.archive.org/web/20250708124907/https://www.theregister.com/AMP/2024/02/09/opinion_column_mozilla_ceo_quits/)
- no answer https://www.catonetworks.com/blog/xz-backdoor-rce-cve-2024-3094-is-the-biggest-supply-chain-attack-since-log4j/ · [archived 2026-05-18](http://web.archive.org/web/20260518071042/https://www.catonetworks.com/blog/xz-backdoor-rce-cve-2024-3094-is-the-biggest-supply-chain-attack-since-log4j/)

**ppl_tech-power.json**

- 404 https://aicommission.org/2026/05/metas-ai-crisis-deepens-inside-the-fight-against-mark-zuckerberg/
- 404 https://finance.yahoo.com/markets/stocks/articles/elon-musk-doge-politics-bets-013142887.html

**ppl_tech-scandals.json**

- no answer https://www.insidephilanthropy.com/home/2024-3-14-post-wework-the-neumanns-are-still-billionaires-whatever-happened-to-their-philanthropy · [archived 2025-09-04](http://web.archive.org/web/20250904205847/https://www.insidephilanthropy.com/home/2024-3-14-post-wework-the-neumanns-are-still-billionaires-whatever-happened-to-their-philanthropy)

**r7_rag-systems.json**

- 404 https://langcopilot.com/posts/2025-09-18-best-rag-frameworks-2026 · [archived 2026-06-09](http://web.archive.org/web/20260609082048/https://langcopilot.com/posts/2025-09-18-best-rag-frameworks-2026)

**r8_economics-money.json**

- 404 https://www.povertyactionlab.org/policy-insight/impact-microcredit

**r8_education-knowledge.json**

- 404 https://en.unesco.org/themes/linguistic-diversity-and-multilingualism
- 404 https://www.hbs.edu/managing-the-future-of-work/Documents/dismissed-by-degrees.pdf · [archived 2026-06-09](http://web.archive.org/web/20260609200813/https://www.hbs.edu/managing-the-future-of-work/Documents/dismissed-by-degrees.pdf)
- 404 https://www.imls.gov/research-evaluation/data-collection/public-libraries-survey
- 404 https://www.pewresearch.org/short-reads/2023/11/16/about-1-in-5-u-s-teens-whove-heard-of-chatgpt-have-used-it-for-schoolwork/
- 404 https://www.rand.org/pubs/research_reports/RR2332.html

**r8_environment-climate.json**

- 404 https://en.wikipedia.org/wiki/C8_Health_Project
- 404 https://en.wikipedia.org/wiki/Stratospheric_Controlled_Perturbation_Experiment
- no answer https://www.rewildingeurope.com/ · [archived 2026-10-19](http://web.archive.org/web/20261019215612/https://rewildingeurope.com/)
- 404 https://www.usbr.gov/lc/region/g4000/hourly/mead-702.html

**r8_law-governance.json**

- 404 https://ec.europa.eu/competition/digital_markets/dma_en
- 404 https://en.wikipedia.org/wiki/Bhe_v._Magistrate,_Khayelitsha
- 404 https://innocenceproject.org/false-guilty-pleas/
- 404 https://www.eff.org/issues/fisa-702
- 404 https://www.justice.gov/atr/case/united-states-v-google-llc-2020
- 404 https://www.law.berkeley.edu/library/robbins/CommonLawCivilLawTraditions.html
- 404 https://www.supremecourt.uk/decided-cases/docs/UKSC_2019_0192_Judgment.pdf

**r8_war-security.json**

- 404 https://en.wikipedia.org/wiki/Rationalist_explanations_for_war
- 404 https://www.cnn.com/2018/08/17/middleeast/us-saudi-yemen-bus-bomb-intl/index.html
- no answer https://www.stopkillerrobots.org/ · [archived 2026-10-12](http://web.archive.org/web/20261012205645/https://www.stopkillerrobots.org/)
- no answer https://www.worldwater.org/water-conflict/ · [archived 2026-10-25](http://web.archive.org/web/20261025092954/https://www.worldwater.org/water-conflict/)

**r9_health-medicine.json**

- 404 https://accessiblemeds.org/resources/reports/2022-access-savings-report
- 404 https://www.ftc.gov/news-events/news/press-releases/2024/02/ftc-ny-attorney-general-secure-court-ruling-vyera-pharma-case-related-5000-price-hike-life-saving

**r9_labor-work.json**

- 404 https://internationalaccord.org/updates/ten-years-since-the-rana-plaza-disaster/
- 404 https://www.givedirectly.org/large-scale-basic-income/
- 404 https://www.ilo.org/resource/news/ilo-convention-child-labour-achieves-universal-ratification
- 404 https://www.kela.fi/web/en/basic-income-experiment · [archived 2022-07-07](http://web.archive.org/web/20220707144133/https://www.kela.fi/web/en/basic-income-experiment)
- no answer https://www.mckinsey.com/featured-insights/future-of-work/jobs-lost-jobs-gained-what-the-future-of-work-will-mean-for-jobs-skills-and-wages · [archived 2026-08-14](http://web.archive.org/web/20260814151500/https://www.mckinsey.com/featured-insights/future-of-work/jobs-lost-jobs-gained-what-the-future-of-work-will-mean-for-jobs-skills-and-wages)
- 404 https://www.osha.gov/aboutosha/history

**r9_media-information.json**

- 404 https://on.substack.com/p/2023-year-in-review
- 404 https://www.justice.gov/file/1035477/download · [archived 2024-03-15](http://web.archive.org/web/20240315011338/https://www.justice.gov/file/1035477/download)
- 404 https://www.justice.gov/opa/pr/wikileaks-founder-julian-assange-charged-superseding-indictment
- no answer https://www.usnewsdeserts.com/ · [archived 2026-10-17](http://web.archive.org/web/20261017153146/https://www.usnewsdeserts.com/)

**xwire2_climate-everything.json**

- no answer https://www.publish.csiro.au/wf/WF19110
- 404 https://www1.bca.gov.sg/buildsg/sustainability/green-mark-certification-scheme · [archived 2026-02-19](http://web.archive.org/web/20260219115106/https://www1.bca.gov.sg/buildsg/sustainability/green-mark-certification-scheme/)

**xwire2_knowledge-control.json**

- 404 https://archive.org/details/studyofamericani00brigiala
- 404 https://www.ala.org/advocacy/banning/book-ban-data
- 404 https://www.ftc.gov/news-events/news/press-releases/2019/07/ftc-imposes-5-billion-penalty-sweeping-new-privacy-restrictions-facebook · [archived 2026-10-22](http://web.archive.org/web/20261022084606/https://www.ftc.gov/news-events/news/press-releases/2019/07/ftc-imposes-5-billion-penalty-sweeping-new-privacy-restrictions-facebook)

**xwire2_money-power.json**

- 404 https://www.supremecourt.gov/opinions/09pdf/08-205.pdf · [archived 2025-09-15](http://web.archive.org/web/20250915101323/https://www.supremecourt.gov/opinions/09pdf/08-205.pdf)
- 404 https://www.treasurydirect.gov/timeline/war-bonds/

**xwire3_systems-control.json**

- 404 https://merics.org/en/report/chinas-social-credit-system-2021
- 404 https://www.aclu.org/documents/school-prison-pipeline-infographic
- 404 https://www.epa.gov/ejscreen · [archived 2025-02-05](http://web.archive.org/web/20250205112736/https://www.epa.gov/ejscreen)
- no answer https://www.pclob.gov/Reports/report-702 · [archived 2020-02-26](http://web.archive.org/web/20200226091733/https://www.pclob.gov/reports/report-702/)
- 404 https://www.theguardian.com/world/2013/jun/21/gchq-cables-secret-world-communications-nsa

**xwire3_unintended-consequences.json**

- 404 https://www.atlanticcouncil.org/blogs/econographics/russia-sanctions-and-the-weaponization-of-finance/
- 404 https://www.eff.org/deeplinks/2022/02/content-moderation-not-just-about-free-speech

**xwire_credit-erasure.json**

- 404 https://www.edpb.europa.eu/our-work-tools/our-documents/other/coordinated-enforcement-action-right-erasure_en
- 404 https://www.nature.com/articles/d41586-023-00032-3

**xwire_ethics-creation.json**

- 404 https://www.atomicarchive.com/resources/documents/beginnings/einstein-szilard.html
- 404 https://www.ftc.gov/legal-library/browse/rules/childrens-online-privacy-protection-rule-coppa · [archived 2026-10-23](http://web.archive.org/web/20261023234851/https://www.ftc.gov/legal-library/browse/rules/childrens-online-privacy-protection-rule-coppa)
- no answer https://www.gnu.org/philosophy/free-sw.en.html · [archived 2026-10-23](http://web.archive.org/web/20261023165055/https://www.gnu.org/philosophy/free-sw.en.html)

**xwire_ideas-weaponized.json**

- 404 https://www.nature.com/articles/s41599-021-00779-6
- 404 https://www.nybooks.com/articles/2011/03/10/worst-way-to-make-history/
- 404 https://www.pbs.org/transistor/album1/shockley/shockrace.html

**xwire_infrastructure-control.json**

- 404 https://www.energy.gov/gdo/articles/department-energy-releases-new-report-assessing-vulnerabilities-large-power
- 404 https://www.gps.gov/applications/timing/ · [archived 2025-09-11](http://web.archive.org/web/20250911140019/https://www.gps.gov/applications/timing/)

**xwire_power-accountability.json**

- 404 https://www.newyorker.com/news/news-desk/the-sackler-family-and-the-art-of-reputation-laundering
- no answer https://www.washingtonpost.com/technology/2023/03/30/tech-nda-whistleblower-impact/

## Rerun

With willow (willow-memory/Willow, the `jeles` add-on):

    python adapters/stdlib/jeles/jeles.py mirror --from jeles/seed --to MIRROR
    python kernel.py init --box BOX --pile MIRROR --key KEY
    python adapters/stdlib/contradictions/contradictions.py --box BOX
    python adapters/stdlib/duplicates/duplicates.py --box BOX
