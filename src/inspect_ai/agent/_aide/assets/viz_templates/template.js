const bgCol = "#F2F0E7";
const accentCol = "#fd4578";

hljs.initHighlightingOnLoad();

const updateTargetDims = () => {
  // width is max-width of `.contentContainer` - its padding
  // return [min(windowWidth, 900 - 80), 700]
  return [windowWidth * (1 / 2), windowHeight];
};

const setCodeAndPlan = (code, plan) => {
  const codeElm = document.getElementById("code");
  if (codeElm) {
    // codeElm.innerText = code;
    codeElm.innerHTML = hljs.highlight(code, { language: "python" }).value;
  }

  const planElm = document.getElementById("plan");
  if (planElm) {
    // planElm.innerText = plan.trim();
    planElm.innerHTML = hljs.highlight(plan, { language: "plaintext" }).value;
  }
};

windowResized = () => {
  resizeCanvas(...updateTargetDims());
  awaitingPostResizeOps = true;
};

const animEase = (t) => 1 - (1 - Math.min(t, 1.0)) ** 5;

// ---- global constants ----

const globalAnimSpeed = 1.1;
const scaleFactor = 0.57;

// ---- global vars ----

let globalTime = 0;
let manualSelection = false;

let currentElemInd = 0;

let treeStructData = <placeholder>

let lastClick = 0;
let firstFrameTime = undefined;

let nodes = [];
let edges = [];

let lastScrollPos = 0;

setup = () => {
  canvas = createCanvas(...updateTargetDims());
};

class Node {
  x;
  y;
  size;
  xT;
  yT;
  xB;
  yB;
  treeInd;
  color;
  relSize;
  animationStart = Number.MAX_VALUE;
  animationProgress = 0;
  isStatic = false;
  hasChildren = false;
  isRootNode = true;
  isStarred = false;
  selected = false;
  renderSize = 10;
  edges = [];
  bgCol;

  constructor(x, y, relSize, treeInd) {
    const minSize = 35;
    const maxSize = 60;

    const maxColor = 10;
    const minColor = 125;

    this.relSize = relSize;
    this.treeInd = treeInd;
    this.size = minSize + (maxSize - minSize) * relSize;
    this.color = minColor + (maxColor - minColor) * relSize;
    this.bgCol = Math.round(Math.max(this.color / 2, 0));

    this.x = x;
    this.y = y;
    this.xT = x;
    this.yT = y - this.size / 2;
    this.xB = x;
    this.yB = y + this.size / 2;

    nodes.push(this);
  }

  startAnimation = (offset = 0) => {
    if (this.animationStart == Number.MAX_VALUE)
      this.animationStart = globalTime + offset;
  };

  child = (node) => {
    let edge = new Edge(this, node);
    this.edges.push(edge);
    edges.push(edge);
    this.hasChildren = true;
    node.isRootNode = false;
    return node;
  };

  render = () => {
    if (globalTime - this.animationStart < 0) return;

    const mouseXlocalCoords = (mouseX - width / 2) / scaleFactor;
    const mouseYlocalCoords = (mouseY - height / 2) / scaleFactor;
    const isMouseOver =
      dist(mouseXlocalCoords, mouseYlocalCoords, this.x, this.y) <
      this.renderSize / 1.5;
    if (isMouseOver) cursor(HAND);
    if (isMouseOver && mouseIsPressed) {
      nodes.forEach((n) => (n.selected = false));
      this.selected = true;
      setCodeAndPlan(
        treeStructData.code[this.treeInd],
        treeStructData.plan[this.treeInd],
      );
      manualSelection = true;
    }

    this.renderSize = this.size;
    if (!this.isStatic) {
      this.animationProgress = animEase(
        (globalTime - this.animationStart) / 1000,
      );
      if (this.animationProgress >= 1) {
        this.isStatic = true;
      } else {
        this.renderSize =
          this.size *
          (0.8 +
            0.2 *
              (-3.33 * this.animationProgress ** 2 +
                4.33 * this.animationProgress));
      }
    }

    fill(this.color);
    if (this.selected) {
      fill(accentCol);
    }

    noStroke();
    square(
      this.x - this.renderSize / 2,
      this.y - this.renderSize / 2,
      this.renderSize,
      10,
    );

    noStroke();
    textAlign(CENTER, CENTER);
    textSize(this.renderSize / 2);
    fill(255);
    // fill(lerpColor(color(accentCol), color(255), this.animationProgress))
    text("{ }", this.x, this.y - 1);
    // DEBUG PRINT:
    // text(round(this.relSize, 2), this.x, this.y - 1)
    // text(this.treeInd, this.x, this.y + 15)

    const dotAnimThreshold = 0.85;
    if (this.isStarred && this.animationProgress >= dotAnimThreshold) {
      let dotAnimProgress =
        (this.animationProgress - dotAnimThreshold) / (1 - dotAnimThreshold);
      textSize(
        ((-3.33 * dotAnimProgress ** 2 + 4.33 * dotAnimProgress) *
          this.renderSize) /
          2,
      );
      if (this.selected) {
        fill(0);
        stroke(0);
      } else {
        fill(accentCol);
        stroke(accentCol);
      }
      strokeWeight((-(dotAnimProgress ** 2) + dotAnimProgress) * 2);
      text("*", this.x + 20, this.y - 11);
      noStroke();
    }

    if (!this.isStatic) {
      fill(bgCol);
      const progressAnimBaseSize = this.renderSize + 5;
      rect(
        this.x - progressAnimBaseSize / 2,
        this.y -
          progressAnimBaseSize / 2 +
          progressAnimBaseSize * this.animationProgress,
        progressAnimBaseSize,
        progressAnimBaseSize * (1 - this.animationProgress),
      );
    }
    if (this.animationProgress >= 0.9) {
      this.edges
        .sort((a, b) => a.color() - b.color())
        .forEach((e, i) => {
          e.startAnimation((i / this.edges.length) ** 2 * 1000);
        });
    }
  };
}

class Edge {
  nodeT;
  nodeB;
  animX = 0;
  animY = 0;
  animationStart = Number.MAX_VALUE;
  animationProgress = 0;
  isStatic = false;
  weight = 0;

  constructor(nodeT, nodeB) {
    this.nodeT = nodeT;
    this.nodeB = nodeB;
    this.weight = 2 + nodeB.relSize * 1;
  }

  color = () => this.nodeB.color;

  startAnimation = (offset = 0) => {
    if (this.animationStart == Number.MAX_VALUE)
      this.animationStart = globalTime + offset;
  };

  render = () => {
    if (globalTime - this.animationStart < 0) return;

    if (!this.isStatic) {
      this.animationProgress = animEase(
        (globalTime - this.animationStart) / 1000,
      );
      if (this.animationProgress >= 1) {
        this.isStatic = true;
        this.animX = this.nodeB.xT;
        this.animY = this.nodeB.yT;
      } else {
        this.animX = bezierPoint(
          this.nodeT.xB,
          this.nodeT.xB,
          this.nodeB.xT,
          this.nodeB.xT,
          this.animationProgress,
        );

        this.animY = bezierPoint(
          this.nodeT.yB,
          (this.nodeT.yB + this.nodeB.yT) / 2,
          (this.nodeT.yB + this.nodeB.yT) / 2,
          this.nodeB.yT,
          this.animationProgress,
        );
      }
    }
    if (this.animationProgress >= 0.97) {
      this.nodeB.startAnimation();
    }

    strokeWeight(this.weight);
    noFill();
    stroke(
      lerpColor(color(bgCol), color(accentCol), this.nodeB.relSize * 1 + 0.7),
    );
    bezier(
      this.nodeT.xB,
      this.nodeT.yB,
      this.nodeT.xB,
      (this.nodeT.yB + this.nodeB.yT) / 2,
      this.animX,
      (this.nodeT.yB + this.nodeB.yT) / 2,
      this.animX,
      this.animY,
    );
  };
}

draw = () => {
  cursor(ARROW);
  frameRate(120);
  if (!firstFrameTime && frameCount <= 1) {
    firstFrameTime = millis();
  }
  // ---- update global animation state ----
  const initialSpeedScalingEaseIO =
    (cos(min((millis() - firstFrameTime) / 8000, 1.0) * PI) + 1) / 2;
  const initialSpeedScalingEase =
    (cos(min((millis() - firstFrameTime) / 8000, 1.0) ** (1 / 2) * PI) + 1) / 2;
  const initAnimationSpeedFactor = 1.0 - 0.4 * initialSpeedScalingEaseIO;
  // update global scaling-aware clock
  globalTime += globalAnimSpeed * initAnimationSpeedFactor * deltaTime;

  if (nodes.length == 0) {
    const spacingHeight = height * 1.3;
    const spacingWidth = width * 1.3;
    treeStructData.layout.forEach((lay, index) => {
      new Node(
        spacingWidth * lay[0] - spacingWidth / 2,
        20 + spacingHeight * lay[1] - spacingHeight / 2,
        1 - treeStructData.metrics[index],
        index,
      );
    });
    treeStructData.edges.forEach((ind) => {
      nodes[ind[0]].child(nodes[ind[1]]);
    });
    nodes.forEach((n) => {
      if (n.isRootNode) n.startAnimation();
    });
    nodes[0].selected = true;
    setCodeAndPlan(
      treeStructData.code[0],
      treeStructData.plan[0],
    )
  }

  const staticNodes = nodes.filter(
    (n) => n.isStatic || n.animationProgress >= 0.7,
  );
  if (staticNodes.length > 0) {
    const largestNode = staticNodes.reduce((prev, current) =>
      prev.relSize > current.relSize ? prev : current,
    );
    if (!manualSelection) {
      if (!largestNode.selected) {
        setCodeAndPlan(
          treeStructData.code[largestNode.treeInd],
          treeStructData.plan[largestNode.treeInd],
        );
      }
      staticNodes.forEach((node) => {
        node.selected = node === largestNode;
      });
    }
  }
  background(bgCol);
  // global animation transforms
  translate(width / 2, height / 2);
  scale(scaleFactor);

  
  // ---- fg render ----
  edges.forEach((e) => e.render());
  nodes.forEach((n) => n.render());
  
};
