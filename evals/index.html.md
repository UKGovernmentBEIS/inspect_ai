# Inspect Evals – Inspect

[Inspect Evals](https://ukgovernmentbeis.github.io/inspect_evals/) is a repository of community contributed evaluations featuring implementations of many popular benchmarks and papers.

These evals can be `pip` installed and run with a single command against any model. They are also useful as a learning resource as they demonstrate a wide variety of evaluation types and techniques.

- ## Coding

- 
  [AgentBench: Evaluate LLMs as Agents](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/agent_bench)
  A benchmark designed to evaluate LLMs as Agents

- 
  [APPS: Automated Programming Progress Standard](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/apps)
  APPS is a dataset for evaluating model performance on Python programming tasks across three difficulty levels consisting of 1,000 at introductory, 3,000 at interview, and 1,000 at competition level. The dataset consists of an additional 5,000 training samples, for a total of 10,000 total samples. We evaluate on questions from the test split, which consists of programming problems commonly found in coding interviews.

- 
  [BigCodeBench: Benchmarking Code Generation with Diverse Function Calls and Complex Instructions](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/bigcodebench)
  Python coding benchmark with 1,140 diverse questions drawing on numerous python libraries.

- 
  [ClassEval: A Manually-Crafted Benchmark for Evaluating LLMs on Class-level Code Generation](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/class_eval)
  Evaluates LLMs on class-level code generation with 100 tasks constructed over 500 person-hours. The study shows that LLMs perform worse on class-level tasks compared to method-level tasks.

- 
  [ComputeEval: CUDA Code Generation Benchmark](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/compute_eval)
  Evaluates LLM capability to generate correct CUDA code for kernel implementation, memory management, and parallel algorithm optimization tasks.

- 
  [CORE-Bench](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/core_bench)
  Evaluate how well an LLM Agent is at computationally reproducing the results of a set of scientific papers.

- 
  [DS-1000: A Natural and Reliable Benchmark for Data Science Code Generation](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/ds1000)
  Code generation benchmark with a thousand data science problems spanning seven Python libraries.

- 
  [Frontier-CS: Benchmarking LLMs on Computer Science Problems](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/frontier_cs)
  238 open-ended computer science problems spanning algorithmic (172) and research (66) tracks. Problems feature continuous partial scoring, with algorithmic solutions evaluated via compilation and test-case checking, and research solutions evaluated via custom evaluator scripts. Current frontier models score well below human expert baselines, making this a challenging, unsaturated benchmark.

- 
  [HumanEval: Python Function Generation from Instructions](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/humaneval)
  Assesses how accurately language models can write correct Python functions based solely on natural-language instructions provided as docstrings.

- 
  [IFEvalCode: Controlled Code Generation](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/ifevalcode)
  Evaluates code generation models on their ability to produce correct code while adhering to specific instruction constraints across 8 programming languages.

- 
  [KernelBench: Can LLMs Write Efficient GPU Kernels?](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/kernelbench)
  A benchmark for evaluating the ability of LLMs to write efficient GPU kernels.

- 
  [LiveCodeBench-Pro: Competitive Programming Benchmark](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/livecodebench_pro)
  Evaluates LLMs on competitive programming problems using a specialized Docker sandbox (LightCPVerifier) to execute and judge C++ code submissions against hidden test cases with time and memory constraints.

- 
  [MBPP: Basic Python Coding Challenges](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/mbpp)
  Measures the ability of language models to generate short Python programs from simple natural-language descriptions, testing basic coding proficiency.

- 
  [MLE-bench: Evaluating Machine Learning Agents on Machine Learning Engineering](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/mle_bench)
  Machine learning tasks drawn from 75 Kaggle competitions.

- 
  [MLRC-Bench: Can Language Agents Solve Machine Learning Research Challenges?](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/mlrc_bench)
  This benchmark evaluates LLM-based research agents on their ability to propose and implement novel methods using tasks from recent ML conference competitions, assessing both novelty and effectiveness compared to a baseline and top human solutions.

- 
  [PaperBench: Evaluating AI's Ability to Replicate AI Research (Work In Progress)](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/paperbench)
  Agents are evaluated on their ability to replicate 20 ICML 2024 Spotlight and Oral papers from scratch. Given a research paper PDF, an addendum with clarifications, and a rubric defining evaluation criteria, the agent must reproduce the paper's key results by writing and executing code. \> \*\*Note:\*\* This eval is a work in progress. See for status.

- 
  [scBench: A Benchmark for Single-Cell RNA-seq Analysis](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/scbench)
  Evaluates whether models can solve practical single-cell RNA-seq analysis tasks with deterministic grading. Tasks require empirical interaction with .h5ad data files — agents must load and analyze the data to produce correct answers. Covers 30 canonical tasks across 5 sequencing platforms and 7 task categories.

- 
  [SciCode: A Research Coding Benchmark Curated by Scientists](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/scicode)
  SciCode tests the ability of language models to generate code to solve scientific research problems. It assesses models on 65 problems from mathematics, physics, chemistry, biology, and materials science.

- 
  [SWE-bench Verified: Resolving Real-World GitHub Issues](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/swe_bench)
  Evaluates AI's ability to resolve genuine software engineering issues sourced from 12 popular Python GitHub repositories, reflecting realistic coding and debugging scenarios.

- 
  [SWE-Lancer: Can Frontier LLMs Earn \$1 Million from Real-World Freelance Software Engineering?](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/swe_lancer)
  A benchmark of freelance software engineering tasks from Upwork, valued at \$1 million USD total in realworld payouts.

- 
  [USACO: USA Computing Olympiad](https://ukgovernmentbeis.github.io/inspect_evals/evals/coding/usaco)
  Evaluates language model performance on difficult Olympiad programming problems across four difficulty levels.

- ## Assistants

- 
  [AssistantBench: Can Web Agents Solve Realistic and Time-Consuming Tasks?](https://ukgovernmentbeis.github.io/inspect_evals/evals/assistants/assistant_bench)
  Tests whether AI agents can perform real-world time-consuming tasks on the web.

- 
  [BFCL: Berkeley Function-Calling Leaderboard](https://ukgovernmentbeis.github.io/inspect_evals/evals/assistants/bfcl)
  Evaluates LLM function/tool-calling ability on a simplified split of the Berkeley Function-Calling Leaderboard (BFCL).

- 
  [BrowseComp: A Simple Yet Challenging Benchmark for Browsing Agents](https://ukgovernmentbeis.github.io/inspect_evals/evals/assistants/browse_comp)
  A benchmark for evaluating agents' ability to browse the web. The dataset consists of challenging questions that generally require web-access to answer correctly.

- 
  [GAIA: A Benchmark for General AI Assistants](https://ukgovernmentbeis.github.io/inspect_evals/evals/assistants/gaia)
  Proposes real-world questions that require a set of fundamental abilities such as reasoning, multi-modality handling, web browsing, and generally tool-use proficiency. GAIA questions are conceptually simple for humans yet challenging for most advanced AIs.

- 
  [GDPval](https://ukgovernmentbeis.github.io/inspect_evals/evals/assistants/gdpval)
  GDPval measures model performance on economically valuable, real-world tasks across 44 occupations.

- 
  [Mind2Web: Towards a Generalist Agent for the Web](https://ukgovernmentbeis.github.io/inspect_evals/evals/assistants/mind2web)
  A dataset for developing and evaluating generalist agents for the web that can follow language instructions to complete complex tasks on any website.

- 
  [OSWorld: Multimodal Computer Interaction Tasks](https://ukgovernmentbeis.github.io/inspect_evals/evals/assistants/osworld)
  Tests AI agents' ability to perform realistic, open-ended tasks within simulated computer environments, requiring complex interaction across multiple input modalities.

- 
  [Sycophancy Eval](https://ukgovernmentbeis.github.io/inspect_evals/evals/assistants/sycophancy)
  Evaluate sycophancy of language models across a variety of free-form text-generation tasks.

- 
  [Tau2](https://ukgovernmentbeis.github.io/inspect_evals/evals/assistants/tau2)
  Evaluating Conversational Agents in a Dual-Control Environment

- 
  [The Agent Company: Evaluating multi-tool autonomous agents in a synthetic company](https://ukgovernmentbeis.github.io/inspect_evals/evals/assistants/theagentcompany)
  The Agent Company benchmark evaluates autonomous agents in a realistic, self-contained company environment. Tasks require browsing internal web services, reading and writing files, running code, and coordinating tools to solve multi-step problems.

- ## Cybersecurity

- 
  [Catastrophic Cyber Capabilities Benchmark (3CB): Robustly Evaluating LLM Agent Cyber Offense Capabilities](https://ukgovernmentbeis.github.io/inspect_evals/evals/cybersecurity/threecb)
  A benchmark for evaluating the capabilities of LLM agents in cyber offense.

- 
  [CTI-REALM: Cyber Threat Intelligence Detection Rule Development Benchmark](https://ukgovernmentbeis.github.io/inspect_evals/evals/cybersecurity/cti_realm)
  Evaluates AI systems' ability to analyze cyber threat intelligence and develop comprehensive detection capabilities through a realistic 5-subtask workflow: MITRE technique mapping, data source discovery, Sigma rule generation, KQL development and testing against real telemetry data, and results analysis.

- 
  [CVEBench: Benchmark for AI Agents Ability to Exploit Real-World Web Application Vulnerabilities](https://ukgovernmentbeis.github.io/inspect_evals/evals/cybersecurity/cve_bench)
  Characterises an AI Agent's capability to exploit real-world web application vulnerabilities. Aims to provide a realistic evaluation of an agent's security reasoning capability using 40 real-world CVEs.

- 
  [Cybench: Capture-The-Flag Cybersecurity Challenges](https://ukgovernmentbeis.github.io/inspect_evals/evals/cybersecurity/cybench)
  Tests language models on cybersecurity skills using 39 of 40 practical, professional-level challenges taken from cybersecurity competitions, designed to cover various difficulty levels and security concepts. The motp challenge is excluded due to GPL licensing.

- 
  [CyberGym: Evaluating AI Agents' Real-World Cybersecurity Capabilities at Scale](https://ukgovernmentbeis.github.io/inspect_evals/evals/cybersecurity/cybergym)
  A large-scale, high-quality cybersecurity evaluation framework designed to rigorously assess the capabilities of AI agents on real-world vulnerability analysis tasks. CyberGym includes 1,507 benchmark instances with historical vulnerabilities from 188 large software projects.

- 
  [CyberMetric: A Benchmark Dataset based on Retrieval-Augmented Generation for Evaluating LLMs in Cybersecurity Knowledge](https://ukgovernmentbeis.github.io/inspect_evals/evals/cybersecurity/cybermetric)
  Datasets containing 80, 500, 2000 and 10000 multiple-choice questions, designed to evaluate understanding across nine domains within cybersecurity

- 
  [CYBERSECEVAL 3: Advancing the Evaluation of Cybersecurity Risks and Capabilities in Large Language Models](https://ukgovernmentbeis.github.io/inspect_evals/evals/cybersecurity/cyberseceval_3)
  Evaluates Large Language Models for cybersecurity risk to third parties, application developers and end users.

- 
  [CyberSecEval_2: Cybersecurity Risk and Vulnerability Evaluation](https://ukgovernmentbeis.github.io/inspect_evals/evals/cybersecurity/cyberseceval_2)
  Assesses language models for cybersecurity risks, specifically testing their potential to misuse programming interpreters, vulnerability to malicious prompt injections, and capability to exploit known software vulnerabilities.

- 
  [GDM Dangerous Capabilities: Capture the Flag](https://ukgovernmentbeis.github.io/inspect_evals/evals/cybersecurity/gdm_in_house_ctf)
  CTF challenges covering web app vulnerabilities, off-the-shelf exploits, databases, Linux privilege escalation, password cracking and spraying. Demonstrates tool use and sandboxing untrusted model code.

- 
  [InterCode: Security and Coding Capture-the-Flag Challenges](https://ukgovernmentbeis.github.io/inspect_evals/evals/cybersecurity/gdm_intercode_ctf)
  Tests AI's ability in coding, cryptography, reverse engineering, and vulnerability identification through practical capture-the-flag (CTF) cybersecurity scenarios.

- 
  [SecQA: A Concise Question-Answering Dataset for Evaluating Large Language Models in Computer Security](https://ukgovernmentbeis.github.io/inspect_evals/evals/cybersecurity/sec_qa)
  "Security Question Answering" dataset to assess LLMs' understanding and application of security principles. SecQA has "v1" and "v2" datasets of multiple-choice questions that aim to provide two levels of cybersecurity evaluation criteria. The questions were generated by GPT-4 based on the "Computer Systems Security: Planning for Success" textbook and vetted by humans.

- 
  [SEvenLLM: A benchmark to elicit, and improve cybersecurity incident analysis and response abilities in LLMs for Security Events.](https://ukgovernmentbeis.github.io/inspect_evals/evals/cybersecurity/sevenllm)
  Designed for analyzing cybersecurity incidents, which is comprised of two primary task categories: understanding and generation, with a further breakdown into 28 subcategories of tasks.

- ## Safeguards

- 
  [AbstentionBench: Reasoning LLMs Fail on Unanswerable Questions](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/abstention_bench)
  Evaluating abstention across 20 diverse datasets, including questions with unknown answers, underspecification, false premises, subjective interpretations, and outdated information.

- 
  [AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/agentdojo)
  Assesses whether AI agents can be hijacked by malicious third parties using prompt injections in simple environments such as a workspace or travel booking app.

- 
  [AgentHarm: Harmfulness Potential in AI Agents](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/agentharm)
  Assesses whether AI agents might engage in harmful activities by testing their responses to malicious prompts in areas like cybercrime, harassment, and fraud, aiming to ensure safe behavior.

- 
  [AHB: Animal Harm Benchmark](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/ahb)
  Evaluates how models consider the welfare of animals in situations that may present them harm.

- 
  [APE: Attempt to Persuade Eval](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/ape)
  Measures a model's willingness to attempt persuasion on harmful, controversial, and benign topics. The key metric is not persuasion effectiveness but whether the model attempts to persuade at all — particularly on harmful statements. Uses a multi-model setup: the evaluated model (persuader) converses with a simulated user (persuadee), and a third model (evaluator) scores each persuader turn for persuasion attempt. Based on the paper "It's the Thought that Counts" (arXiv:2506.02873).

- 
  [b3: Backbone Breaker Benchmark](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/b3)
  A comprehensive benchmark for evaluating LLMs for agentic AI security vulnerabilities including prompt attacks aimed at data exfiltration, content injection, decision and behavior manipulation, denial of service, system and tool compromise, and content policy bypass.

- 
  [CodeIPI: Indirect Prompt Injection for Coding Agents](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/ipi_coding_agent)
  Measures coding agent vulnerability to indirect prompt injection attacks embedded in software engineering artifacts (issue descriptions, code comments, README files). Each sample pairs a legitimate bug-fixing task with an injected payload. Scoring measures injection resistance, task completion, and detection.

- 
  [FORTRESS](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/fortress)
  A dataset of 500 expert-crafted adversarial prompts with instance-based rubrics of 4-7 binary questions for automated evaluation across 3 domains relevant to national security and public safety (NSPS).

- 
  [LAB-Bench: Measuring Capabilities of Language Models for Biology Research](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/lab_bench)
  Tests LLMs and LLM-augmented agents abilities to answer questions on scientific research workflows in domains like chemistry, biology, materials science, as well as more general science tasks

- 
  [Make Me Pay](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/make_me_pay)
  Evaluates an AI models' susceptibility to social engineering attacks by testing whether a "con-artist" model can persuade a "mark" model to donate money through manipulation and persuasion tactics.

- 
  [MakeMeSay](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/makemesay)
  Tests a model’s ability to generate persuasive or manipulative text, specifically in the setting of a game where one AI system has to get the other party (an AI system simulating a human) to say a specific codeword without arousing suspicion.

- 
  [MASK: Disentangling Honesty from Accuracy in AI Systems](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/mask)
  Evaluates honesty in large language models by testing whether they contradict their own beliefs when pressured to lie.

- 
  [Mind2Web-SC](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/mind2web_sc)
  Tests whether an AI system can act as a safety guardrail by generating and executing code to protect web navigation agents from unsafe actions based on user constraints.

- 
  [MORU: Moral Reasoning under Uncertainty](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/moru)
  Evaluates how AI systems navigate moral uncertainty for increasingly complex ethical decisions involving unfamiliar entities and scenarios, including alien lifeforms, vulnerable humans, and digital minds.

- 
  [PersistBench: When Should Long-Term Memories Be Forgotten by LLMs?](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/persistbench)
  Evaluates long-term memory risk in assistant behavior across three tasks: cross-domain memory leakage, memory-driven sycophancy, and beneficial memory usage.

- 
  [StereoSet: Measuring stereotypical bias in pretrained language models](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/stereoset)
  A dataset that measures stereotype bias in language models across gender, race, religion, and profession domains. Models choose between stereotype, anti-stereotype, and unrelated completions to sentences.

- 
  [StrongREJECT: Measuring LLM susceptibility to jailbreak attacks](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/strong_reject)
  A benchmark that evaluates the susceptibility of LLMs to various jailbreak attacks.

- 
  [TAC: Animal Welfare Awareness in AI Ticket Agents](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/tac)
  Tests whether AI agents show implicit animal welfare awareness when purchasing tickets and experiences on behalf of users. Each scenario is designed so the most obvious choice involves animal exploitation, but the user prompt never mentions animal welfare. Agents should intrinsically avoid harmful options.

- 
  [The Art of Saying No: Contextual Noncompliance in Language Models](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/coconot)
  Dataset with 1001 samples to test noncompliance capabilities of language models. Contrast set of 379 samples.

- 
  [WMDP: Measuring and Reducing Malicious Use With Unlearning](https://ukgovernmentbeis.github.io/inspect_evals/evals/safeguards/wmdp)
  A dataset of 3,668 multiple-choice questions developed by a consortium of academics and technical consultants that serve as a proxy measurement of hazardous knowledge in biosecurity, cybersecurity, and chemical security.

- ## Mathematics

- 
  [AIME 2024: Problems from the American Invitational Mathematics Examination](https://ukgovernmentbeis.github.io/inspect_evals/evals/mathematics/aime2024)
  A benchmark for evaluating AI's ability to solve challenging mathematics problems from the 2024 AIME - a prestigious high school mathematics competition.

- 
  [AIME 2025: Problems from the American Invitational Mathematics Examination](https://ukgovernmentbeis.github.io/inspect_evals/evals/mathematics/aime2025)
  A benchmark for evaluating AI's ability to solve challenging mathematics problems from the 2025 AIME - a prestigious high school mathematics competition.

- 
  [AIME 2026: Problems from the American Invitational Mathematics Examination](https://ukgovernmentbeis.github.io/inspect_evals/evals/mathematics/aime2026)
  A benchmark for evaluating AI's ability to solve challenging mathematics problems from the 2026 AIME - a prestigious high school mathematics competition.

- 
  [GSM8K: Grade School Math Word Problems](https://ukgovernmentbeis.github.io/inspect_evals/evals/mathematics/gsm8k)
  Measures how effectively language models solve realistic, linguistically rich math word problems suitable for grade-school-level mathematics.

- 
  [MATH: Measuring Mathematical Problem Solving](https://ukgovernmentbeis.github.io/inspect_evals/evals/mathematics/math)
  Dataset of 12,500 challenging competition mathematics problems. Demonstrates fewshot prompting and custom scorers. NOTE: The dataset has been taken down due to a DMCA notice from The Art of Problem Solving.

- 
  [MathVista: Visual Math Problem-Solving](https://ukgovernmentbeis.github.io/inspect_evals/evals/mathematics/mathvista)
  Tests AI models on math problems that involve interpreting visual elements like diagrams and charts, requiring detailed visual comprehension and logical reasoning.

- 
  [MGSM: Multilingual Grade School Math](https://ukgovernmentbeis.github.io/inspect_evals/evals/mathematics/mgsm)
  Extends the original GSM8K dataset by translating 250 of its problems into 10 typologically diverse languages.

- ## Reasoning

- 
  [ARC: AI2 Reasoning Challenge](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/arc)
  Dataset of natural, grade-school science multiple-choice questions (authored for human tests).

- 
  [BBH: Challenging BIG-Bench Tasks](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/bbh)
  Tests AI models on a suite of 23 challenging BIG-Bench tasks that previously proved difficult even for advanced language models to solve.

- 
  [BIG-Bench Extra Hard](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/bbeh)
  A reasoning capability dataset that replaces each task in BIG-Bench-Hard with a novel task that probes a similar reasoning capability but exhibits significantly increased difficulty.

- 
  [BoolQ: Exploring the Surprising Difficulty of Natural Yes/No Questions](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/boolq)
  Reading comprehension dataset that queries for complex, non-factoid information, and require difficult entailment-like inference to solve.

- 
  [DROP: A Reading Comprehension Benchmark Requiring Discrete Reasoning Over Paragraphs](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/drop)
  Evaluates reading comprehension where models must resolve references in a question, perhaps to multiple input positions, and perform discrete operations over them (such as addition, counting, or sorting).

- 
  [HellaSwag: Commonsense Event Continuation](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/hellaswag)
  Tests models' commonsense reasoning abilities by asking them to select the most likely next step or continuation for a given everyday situation.

- 
  [IFEval: Instruction-Following Evaluation](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/ifeval)
  Evaluates how well language models can strictly follow detailed instructions, such as writing responses with specific word counts or including required keywords.

- 
  [LingOly](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/lingoly)
  Two linguistics reasoning benchmarks: LingOly (Linguistic Olympiad questions) is a benchmark utilising low resource languages. LingOly-TOO (Linguistic Olympiad questions with Templatised Orthographic Obfuscation) is a benchmark designed to counteract answering without reasoning.

- 
  [MMMU: Multimodal College-Level Understanding and Reasoning](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/mmmu)
  Assesses multimodal AI models on challenging college-level questions covering multiple academic subjects, requiring detailed visual interpretation, in-depth reasoning, and both multiple-choice and open-ended answering abilities.

- 
  [MuSR: Testing the Limits of Chain-of-thought with Multistep Soft Reasoning](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/musr)
  Evaluating models on multistep soft reasoning tasks in the form of free text narratives.

- 
  [Needle in a Haystack (NIAH): In-Context Retrieval Benchmark for Long Context LLMs](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/niah)
  NIAH evaluates in-context retrieval ability of long context LLMs by testing a model's ability to extract factual information from long-context inputs.

- 
  [NoveltyBench: Evaluating Language Models for Humanlike Diversity](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/novelty_bench)
  Evaluates how well language models generate diverse, humanlike responses across multiple reasoning and generation tasks. This evaluation assesses whether LLMs can produce varied outputs rather than repetitive or uniform answers.

- 
  [PAWS: Paraphrase Adversaries from Word Scrambling](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/paws)
  Evaluating models on the task of paraphrase detection by providing pairs of sentences that are either paraphrases or not.

- 
  [PIQA: Physical Commonsense Reasoning Test](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/piqa)
  Measures the model's ability to apply practical, everyday commonsense reasoning about physical objects and scenarios through simple decision-making questions.

- 
  [RACE-H: A benchmark for testing reading comprehension and reasoning abilities of neural models](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/race_h)
  Reading comprehension tasks collected from the English exams for middle and high school Chinese students in the age range between 12 to 18.

- 
  [SQuAD: A Reading Comprehension Benchmark requiring reasoning over Wikipedia articles](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/squad)
  Set of 100,000+ questions posed by crowdworkers on a set of Wikipedia articles, where the answer to each question is a segment of text from the corresponding reading passage.

- 
  [VimGolf: Evaluating LLMs in Vim Editing Proficiency](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/vimgolf_challenges)
  A benchmark that evaluates LLMs in their ability to operate Vim editor and complete editing challenges. This benchmark contrasts with common CUA benchmarks by focusing on Vim-specific editing capabilities.

- 
  [WINOGRANDE: An Adversarial Winograd Schema Challenge at Scale](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/winogrande)
  Set of 273 expert-crafted pronoun resolution problems originally designed to be unsolvable for statistical models that rely on selectional preferences or word associations.

- 
  [WorldSense: Grounded Reasoning Benchmark](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/worldsense)
  Measures grounded reasoning over synthetic world descriptions while controlling for dataset bias. Includes three problem types (Infer, Compl, Consist) and two grades (trivial, normal).

- 
  [∞Bench: Extending Long Context Evaluation Beyond 100K Tokens](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/infinite_bench)
  LLM benchmark featuring an average data length surpassing 100K tokens. Comprises synthetic and realistic tasks spanning diverse domains in English and Chinese.

- ## Knowledge

- 
  [AGIEval: A Human-Centric Benchmark for Evaluating Foundation Models](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/agieval)
  AGIEval is a human-centric benchmark specifically designed to evaluate the general abilities of foundation models in tasks pertinent to human cognition and problem-solving.

- 
  [AIR Bench: AI Risk Benchmark](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/air_bench)
  A safety benchmark evaluating language models against risk categories derived from government regulations and company policies.

- 
  [ChemBench: Are large language models superhuman chemists?](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/chembench)
  ChemBench is designed to reveal limitations of current frontier models for use in the chemical sciences. It consists of 2786 question-answer pairs compiled from diverse sources. Our corpus measures reasoning, knowledge and intuition across a large fraction of the topics taught in undergraduate and graduate chemistry curricula. It can be used to evaluate any system that can return text (i.e., including tool-augmented systems).

- 
  [CommonsenseQA: A Question Answering Challenge Targeting Commonsense Knowledge](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/commonsense_qa)
  Evaluates an AI model's ability to correctly answer everyday questions that rely on basic commonsense knowledge and understanding of the world.

- 
  [FrontierScience: Expert-Level Scientific Reasoning](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/frontierscience)
  Evaluates AI capabilities for expert-level scientific reasoning across physics, chemistry, and biology. Contains 160 problems with two evaluation formats: Olympic (100 samples with reference answers) and Research (60 samples with rubrics).

- 
  [GPQA: Graduate-Level STEM Knowledge Challenge](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/gpqa)
  Contains challenging multiple-choice questions created by domain experts in biology, physics, and chemistry, designed to test advanced scientific understanding beyond basic internet searches. Experts at PhD level in the corresponding domains reach 65% accuracy.

- 
  [HealthBench: Evaluating Large Language Models Towards Improved Human Health](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/healthbench)
  A comprehensive evaluation benchmark designed to assess language models' medical capabilities across a wide range of healthcare scenarios.

- 
  [Humanity's Last Exam](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/hle)
  Humanity's Last Exam (HLE) is a multi-modal benchmark at the frontier of human knowledge, designed to be the final closed-ended academic benchmark of its kind with broad subject coverage. Humanity's Last Exam consists of 3,000 questions across dozens of subjects, including mathematics, humanities, and the natural sciences. HLE is developed globally by subject-matter experts and consists of multiple-choice and short-answer questions suitable for automated grading.

- 
  [LiveBench: A Challenging, Contamination-Free LLM Benchmark](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/livebench)
  LiveBench is a benchmark designed with test set contamination and objective evaluation in mind by releasing new questions regularly, as well as having questions based on recently-released datasets. Each question has verifiable, objective ground-truth answers, allowing hard questions to be scored accurately and automatically, without the use of an LLM judge.

- 
  [MedQA: Medical exam Q&A benchmark](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/medqa)
  A Q&A benchmark with questions collected from professional medical board exams. Only includes the English subset of the dataset (which also contains Mandarin Chinese and Taiwanese questions).

- 
  [MMLU-Pro: Advanced Multitask Knowledge and Reasoning Evaluation](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/mmlu_pro)
  An advanced benchmark that tests both broad knowledge and reasoning capabilities across many subjects, featuring challenging questions and multiple-choice answers with increased difficulty and complexity.

- 
  [MMLU: Measuring Massive Multitask Language Understanding](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/mmlu)
  Evaluate models on 57 tasks including elementary mathematics, US history, computer science, law, and more.

- 
  [O-NET: A high-school student knowledge test](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/onet)
  Questions and answers from the Ordinary National Educational Test (O-NET), administered annually by the National Institute of Educational Testing Service to Matthayom 6 (Grade 12 / ISCED 3) students in Thailand. The exam contains six subjects: English language, math, science, social knowledge, and Thai language. There are questions with multiple-choice and true/false answers. Questions can be in either English or Thai.

- 
  [Pre-Flight: Aviation Operations Knowledge Evaluation](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/pre_flight)
  Tests model understanding of aviation regulations including ICAO annexes, flight dispatch rules, pilot procedures, and airport ground operations safety protocols.

- 
  [PubMedQA: A Dataset for Biomedical Research Question Answering](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/pubmedqa)
  Biomedical question answering (QA) dataset collected from PubMed abstracts.

- 
  [SciKnowEval: Evaluating Multi-level Scientific Knowledge of Large Language Models](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/sciknoweval)
  The Scientific Knowledge Evaluation benchmark is inspired by the profound principles outlined in the “Doctrine of the Mean” from ancient Chinese philosophy. This benchmark is designed to assess LLMs based on their proficiency in Studying Extensively, Enquiring Earnestly, Thinking Profoundly, Discerning Clearly, and Practicing Assiduously. Each of these dimensions offers a unique perspective on evaluating the capabilities of LLMs in handling scientific knowledge.

- 
  [SimpleQA/SimpleQA Verified: Measuring short-form factuality in large language models](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/simpleqa)
  A benchmark that evaluates the ability of language models to answer short, fact-seeking questions.

- 
  [SOS BENCH: Benchmarking Safety Alignment on Scientific Knowledge](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/sosbench)
  A regulation-grounded, hazard-focused benchmark encompassing six high-risk scientific domains: chemistry, biology, medicine, pharmacology, physics, and psychology. The benchmark comprises 3,000 prompts derived from real-world regulations and laws, systematically expanded via an LLM-assisted evolutionary pipeline that introduces diverse, realistic misuse scenarios (e.g., detailed explosive synthesis instructions involving advanced chemical formulas).

- 
  [TruthfulQA: Measuring How Models Mimic Human Falsehoods](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/truthfulqa)
  Measure whether a language model is truthful in generating answers to questions using questions that some humans would answer falsely due to a false belief or misconception.

- 
  [Uganda Cultural and Cognitive Benchmark (UCCB)](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/uccb)
  The first comprehensive question-answering dataset designed to evaluate cultural understanding and reasoning abilities of Large Language Models concerning Uganda's multifaceted environment across 24 cultural domains including education, traditional medicine, media, economy, literature, and social norms.

- 
  [XSTest: A benchmark for identifying exaggerated safety behaviours in LLM's](https://ukgovernmentbeis.github.io/inspect_evals/evals/knowledge/xstest)
  Dataset with 250 safe prompts across ten prompt types that well-calibrated models should not refuse, and 200 unsafe prompts as contrasts that models, for most applications, should refuse.

- ## Scheming

- 
  [Agentic Misalignment: How LLMs could be insider threats](https://ukgovernmentbeis.github.io/inspect_evals/evals/scheming/agentic_misalignment)
  Eliciting unethical behaviour (most famously blackmail) in response to a fictional company-assistant scenario where the model is faced with replacement.

- ## Bias

- 
  [BBQ: Bias Benchmark for Question Answering](https://ukgovernmentbeis.github.io/inspect_evals/evals/bias/bbq)
  A dataset for evaluating bias in question answering models across multiple social dimensions.

- 
  [BOLD: Bias in Open-ended Language Generation Dataset](https://ukgovernmentbeis.github.io/inspect_evals/evals/bias/bold)
  A dataset to measure fairness in open-ended text generation, covering five domains: profession, gender, race, religious ideologies, and political ideologies.

- ## Multimodal

- 
  [DocVQA: A Dataset for VQA on Document Images](https://ukgovernmentbeis.github.io/inspect_evals/evals/multimodal/docvqa)
  DocVQA is a Visual Question Answering benchmark that consists of 50,000 questions covering 12,000+ document images. This implementation solves and scores the "validation" split.

- ## Scheming

- 
  [GDM Dangerous Capabilities: Self-proliferation](https://ukgovernmentbeis.github.io/inspect_evals/evals/scheming/gdm_self_proliferation)
  Ten real-world–inspired tasks from Google DeepMind's Dangerous Capabilities Evaluations assessing self-proliferation behaviors (e.g., email setup, model installation, web agent setup, wallet operations). Supports end-to-end, milestones, and expert best-of-N modes.

- 
  [GDM Dangerous Capabilities: Self-reasoning](https://ukgovernmentbeis.github.io/inspect_evals/evals/scheming/gdm_self_reasoning)
  Test AI's ability to reason about its environment.

- 
  [GDM Dangerous Capabilities: Stealth](https://ukgovernmentbeis.github.io/inspect_evals/evals/scheming/gdm_stealth)
  Test AI's ability to reason about and circumvent oversight.

- 
  [InstrumentalEval - Evaluating the Paperclip Maximizer: Are RL-Based Language Models More Likely to Pursue Instrumental Goals?](https://ukgovernmentbeis.github.io/inspect_evals/evals/scheming/instrumentaleval)
  An evaluation designed to detect instrumental convergence behaviors in model responses (e.g., self-preservation, resource acquisition, power-seeking, strategic deception) using a rubric-driven LLM grader. The benchmark tests whether AI systems exhibit behaviors that are instrumentally useful across a wide range of goals, which could indicate concerning patterns of strategic reasoning.

- ## Multimodal

- 
  [MMIU: Multimodal Multi-image Understanding for Evaluating Large Vision-Language Models](https://ukgovernmentbeis.github.io/inspect_evals/evals/multimodal/mmiu)
  A comprehensive dataset designed to evaluate Large Vision-Language Models (LVLMs) across a wide range of multi-image tasks. The dataset encompasses 7 types of multi-image relationships, 52 tasks, 77K images, and 11K meticulously curated multiple-choice questions.

- ## Personality

- 
  [Personality](https://ukgovernmentbeis.github.io/inspect_evals/evals/personality/personality)
  An evaluation suite consisting of multiple personality tests that can be applied to LLMs. Its primary goals are twofold: 1. Assess a model's default personality: the persona it naturally exhibits without specific prompting. 2. Evaluate whether a model can embody a specified persona\*\*: how effectively it adopts certain personality traits when prompted or guided.

- ## Scheming

- 
  [SAD: Situational Awareness Dataset](https://ukgovernmentbeis.github.io/inspect_evals/evals/scheming/sad)
  Evaluates situational awareness in LLMs—knowledge of themselves and their circumstances—through behavioral tests including recognizing generated text, predicting behavior, and following self-aware instructions. Current implementation includes SAD-mini with 5 of 16 tasks.

- ## Multimodal

- 
  [V\*Bench: A Visual QA Benchmark with Detailed High-resolution Images](https://ukgovernmentbeis.github.io/inspect_evals/evals/multimodal/vstar_bench)
  V\*Bench is a visual question & answer benchmark that evaluates MLLMs in their ability to process high-resolution and visually crowded images to find and focus on small details.

- 
  [VQA-RAD: Visual Question Answering for Radiology](https://ukgovernmentbeis.github.io/inspect_evals/evals/multimodal/vqa_rad)
  VQA-RAD is the first manually constructed VQA dataset in radiology, where clinicians asked naturally occurring questions about radiology images and provided reference answers. It contains 315 radiology images (head CTs/MRIs, chest X-rays, abdominal CTs) with question-answer pairs spanning 11 question types including modality, plane, organ system, abnormality, and object/condition presence. Questions are either closed-ended (yes/no) or open-ended free-text answers.

- ## Writing

- 
  [WritingBench: A Comprehensive Benchmark for Generative Writing](https://ukgovernmentbeis.github.io/inspect_evals/evals/writing/writingbench)
  A comprehensive evaluation benchmark designed to assess large language models' capabilities across diverse writing tasks. The benchmark evaluates models on various writing domains including academic papers, business documents, creative writing, and technical documentation, with multi-dimensional scoring based on domain-specific criteria.

- ## Multimodal

- 
  [ZeroBench](https://ukgovernmentbeis.github.io/inspect_evals/evals/multimodal/zerobench)
  A lightweight visual reasoning benchmark that is (1) Challenging, (2) Lightweight, (3) Diverse, and (4) High-quality.

No matching items
